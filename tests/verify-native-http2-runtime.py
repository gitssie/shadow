"""Run production native HTTP/2 wrappers against recording original functions."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/Transport/NativeHTTP2.m").read_text()
wrappers = source[source.index("typedef struct { int age"):source.index("BOOL SHDWNativeHTTP2Prepare(")]
setup = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include "NativeHTTP2.h"
#undef ptrauth_strip
#undef ptrauth_sign_unauthenticated
#define ptrauth_strip(p,k) (p)
#define ptrauth_sign_unauthenticated(p,k,d) (p)
static const char *callerImage;
static BOOL refuseAllocation;
static void *testCalloc(size_t count,size_t size) { return refuseAllocation ? NULL : calloc(count,size); }
#define calloc testCalloc
static int mockDladdr(const void *pc, Dl_info *image) {
  (void)pc; image->dli_fname=callerImage; return callerImage != NULL;
}
#define dladdr mockDladdr
static void SHDWCurlTrace(NSString *stage,id request,NSDictionary *details) {
  (void)stage; (void)request; (void)details;
}
'''
tests = r'''
static BOOL tracked(void *session) { return sessionConfiguration(session, YES, NULL, NULL); }
static SHDWH2Priority savedPriorityValue;
static SHDWH2Configuration profiles[2];
static int profileUsers[3];
static unsigned resolverCalls;
static BOOL resolveProfile(void *user, SHDWH2Configuration *out) {
  resolverCalls++;
  for(unsigned i=0;i<3;i++) if(user==&profileUsers[i]) {
    if(i==2) { memset(out,0,sizeof(*out)); return YES; }
    *out=profiles[i]; return YES;
  }
  return NO;
}

static unsigned settingCalls,windowCalls,absoluteCalls,requestCalls,headerCalls,priorityCalls,deleteCalls;
static int settingsResult,allowed=1,constructorResult;
static unsigned constructorCalls,constructorKind;
static void *nextSession,**savedOutput;
static const void *savedCallbacks,*savedOptions,*savedMemory;
static void *savedConstructorUser;
static int newRecord(unsigned kind,void **out,const void *callbacks,void *user,const void *options,const void *memory) {
  constructorCalls++; constructorKind=kind; savedOutput=out; savedCallbacks=callbacks;
  savedConstructorUser=user; savedOptions=options; savedMemory=memory;
  if(out) *out=nextSession;
  return constructorResult;
}
static int originalNew2(void **out,const void *callbacks,void *user,const void *options) {
  return newRecord(2,out,callbacks,user,options,NULL);
}
static SHDWH2Setting savedSettings[128];
static size_t savedSettingCount,savedHeaderCount;
static SHDWH2Header savedHeaders[16];
static const SHDWH2Header *savedHeaderPointer;
static const void *savedPriority,*savedBody,*nativePriority;
static void *savedUser,*savedSession;
static uint8_t savedFlags;
static int32_t savedStream,savedWindow;
static int allowClient(void *session) { (void)session; return allowed; }
static int originalSettings(void *session,uint8_t flags,const SHDWH2Setting *iv,size_t count) {
  settingCalls++; savedSession=session; savedFlags=flags; savedSettingCount=count;
  assert(count<=128); if(count) memcpy(savedSettings,iv,count*sizeof(*iv)); return settingsResult;
}
static int originalWindow(void *session,uint8_t flags,int32_t stream,int32_t increment) {
  windowCalls++; savedSession=session; savedFlags=flags; savedStream=stream; savedWindow=increment; return 17;
}
static int originalAbsolute(void *session,uint8_t flags,int32_t stream,int32_t size) {
  absoluteCalls++; savedSession=session; savedFlags=flags; savedStream=stream; savedWindow=size; return 18;
}
static void recordHeaders(void *session,const void *priority,const SHDWH2Header *headers,size_t count,void *user) {
  savedSession=session; savedPriority=priority; if(priority && priority!=nativePriority) savedPriorityValue=*(const SHDWH2Priority *)priority; savedUser=user; savedHeaderCount=count;
  savedHeaderPointer=headers; assert(count<=16); memcpy(savedHeaders,headers,count*sizeof(*headers));
}
static int32_t originalRequest(void *session,const void *priority,const SHDWH2Header *headers,
                               size_t count,const void *body,void *user) {
  requestCalls++; savedBody=body; recordHeaders(session,priority,headers,count,user); return 23;
}
static int32_t originalHeaders(void *session,uint8_t flags,int32_t stream,const void *priority,
                               const SHDWH2Header *headers,size_t count,void *user) {
  headerCalls++; savedFlags=flags; savedStream=stream; recordHeaders(session,priority,headers,count,user); return 25;
}
static int originalPriority(void *session,uint8_t flags,int32_t stream,const void *priority) {
  priorityCalls++; savedSession=session; savedFlags=flags; savedStream=stream; savedPriority=priority; return 19;
}
static void originalDelete(void *session) { deleteCalls++; savedSession=session; }
static SHDWH2Header h(const char *name,const char *value,uint8_t flags) {
  SHDWH2Header result={(uint8_t *)name,(uint8_t *)value,strlen(name),strlen(value),flags}; return result;
}
static void same(SHDWH2Header a,SHDWH2Header b) {
  assert(a.name==b.name && a.value==b.value && a.namelen==b.namelen && a.valuelen==b.valuelen && a.flags==b.flags);
}
static void initial(void *session) {
  nextSession=session; void *output=NULL;
  assert(createSession2(&output,NULL,NULL,NULL)==0 && output==session && !tracked(session));
  // Creation alone must not activate header/window mutation before SETTINGS.
  assert(updateWindow(session,0,0,10485760)==17 && savedWindow==10485760);
  SHDWH2Setting baseline[]={{4,2097152},{3,100}};
  assert(setSettings(session,0,baseline,2)==0);
  assert(tracked(session) && savedSettingCount==4);
  assert(savedSettings[0].id==2 && savedSettings[0].value==0);
  assert(savedSettings[1].id==3 && savedSettings[1].value==100);
  assert(savedSettings[2].id==4 && savedSettings[2].value==2097152);
  assert(savedSettings[3].id==9 && savedSettings[3].value==1);
}
int main(void) { @autoreleasepool {
  (void)library; (void)installed;
  assert(SHDWH2ConfigurationParse(&configuration,"2:0;3:100;4:2097152;9:1","msap",10420225,256,0,1));
  originals[0]=(void *)originalSettings; originals[1]=(void *)originalWindow;
  originals[2]=(void *)originalAbsolute; originals[3]=(void *)originalRequest;
  originals[4]=(void *)originalHeaders; originals[5]=(void *)originalPriority; originals[6]=(void *)originalDelete;
  originals[7]=(void *)originalNew2;
  clientAllowed=allowClient;
  int sessionToken=0,unknownToken=0,priorityToken=0,bodyToken=0,userToken=0;
  nativePriority=&priorityToken;
  void *session=&sessionToken,*unknown=&unknownToken;
  SHDWH2Setting baseline[]={{4,2097152},{3,100}};
  SHDWH2Header headers[]={h(":path","/",6),h(":authority","example.test",2),h(":method","POST",4),
                         h(":scheme","https",0),h("cookie","a=1",6),h("cookie","b=2",2)};
  callerImage="/System/Library/Frameworks/CFNetwork.framework/CFNetwork";
  enabled=0;
  assert(setSettings(session,0,baseline,2)==0 && !tracked(session) && savedSettingCount==2);
  enabled=1;
  const char *rejected[]={NULL,"/Applications/App.app/App","/usr/lib/libcurl.dylib"};
  for(size_t i=0;i<sizeof(rejected)/sizeof(*rejected);i++) {
    callerImage=rejected[i];
    assert(setSettings(session,0,baseline,2)==0 && !tracked(session) && savedSettingCount==2);
  }
  callerImage="/System/Library/Frameworks/Network.framework/Network";
  allowed=0;
  assert(setSettings(session,0,baseline,2)==0 && !tracked(session) && savedSettingCount==2);
  allowed=1;
  assert(setSettings(session,1,baseline,2)==0 && !tracked(session) && savedFlags==1);
  // A native caller issuing later SETTINGS on a preexisting session stays untouched.
  assert(setSettings(session,0,baseline,2)==0 && savedSettingCount==2 && !tracked(session));
  initial(session);
  assert(setSettings(session,0,baseline,2)==0 && savedSettingCount==2);
  assert(updateWindow(unknown,0,0,10485760)==17 && savedWindow==10485760 && !tracked(unknown));
  assert(updateWindow(session,0,3,10485760)==17 && savedWindow==10485760 && savedStream==3);
  assert(updateWindow(session,0,0,10485760)==17 && savedWindow==10420225);
  assert(updateWindow(session,0,0,10485760)==17 && savedWindow==10485760);
  assert(absoluteWindow(session,0,0,1234)==18 && savedWindow==1234); /* already claimed */

  assert(submitRequest(session,&priorityToken,headers,6,&bodyToken,&userToken)==23);
  assert(savedSession==session && !savedPriority && savedBody==&bodyToken && savedUser==&userToken && savedHeaderCount==6);
  size_t order[]={2,3,1,0,4,5};
  for(size_t i=0;i<6;i++) same(savedHeaders[i],headers[order[i]]);
  assert(submitHeaders(session,0x25,7,&priorityToken,headers,6,&userToken)==25);
  assert(savedFlags==5 && savedStream==7 && !savedPriority && savedUser==&userToken);
  for(size_t i=0;i<6;i++) same(savedHeaders[i],headers[order[i]]);
  unsigned previousPriorities=priorityCalls;
  assert(submitPriority(session,0,7,&priorityToken)==0 && priorityCalls==previousPriorities);
  assert(submitRequest(unknown,&priorityToken,headers,6,&bodyToken,&userToken)==23);
  assert(savedHeaderPointer==headers && savedPriority==&priorityToken && savedBody==&bodyToken && savedUser==&userToken);
  assert(submitHeaders(unknown,0x25,7,&priorityToken,headers,6,&userToken)==25);
  assert(savedFlags==0x25 && savedPriority==&priorityToken && savedHeaderPointer==headers);
  assert(submitPriority(unknown,0,7,&priorityToken)==19 && priorityCalls==previousPriorities+1);
  callerImage="/Applications/App.app/App";
  assert(submitRequest(session,&priorityToken,headers,6,&bodyToken,&userToken)==23 && savedPriority==&priorityToken && savedHeaderPointer==headers);
  assert(submitHeaders(session,0x25,7,&priorityToken,headers,6,&userToken)==25 && savedFlags==0x25 && savedPriority==&priorityToken);
  assert(submitPriority(session,0,7,&priorityToken)==19);
  enabled=0; callerImage="/System/Library/Frameworks/CFNetwork.framework/CFNetwork";
  assert(submitRequest(session,&priorityToken,headers,6,&bodyToken,&userToken)==23 && savedPriority==&priorityToken);
  enabled=1;

  deleteSession(session); assert(!tracked(session) && deleteCalls==1);
  initial(session); /* same pointer must behave as a fresh connection */
  assert(absoluteWindow(session,0,0,65535)==18 && savedWindow==10485760);
  assert(absoluteWindow(session,0,0,1234)==18 && savedWindow==1234);
  deleteSession(session);
  nextSession=session; void *failedSettingsOutput=NULL;
  assert(createSession2(&failedSettingsOutput,NULL,NULL,NULL)==0 && failedSettingsOutput==session);
  settingsResult=-901;
  assert(setSettings(session,0,baseline,2)==-901 && !tracked(session));
  assert(updateWindow(session,0,0,10485760)==17 && savedWindow==10485760);
  settingsResult=0; callerImage="/usr/lib/libnetwork.dylib";
  initial(session);
  assert(updateWindow(session,0,0,10485760)==17 && savedWindow==10420225);
  deleteSession(session); assert(!sessions);

  int callbacks=0,options=0,constructorUser=0;
  {
    void *output=NULL; nextSession=session;
    int result = createSession2(&output,&callbacks,&constructorUser,&options);
    assert(result==0 && output==session && constructorKind==2 && savedOutput==&output);
    assert(savedCallbacks==&callbacks && savedConstructorUser==&constructorUser);
    assert(savedOptions==&options && savedMemory==NULL);
    assert(!tracked(session));
    assert(submitPriority(session,0,7,&priorityToken)==19);
    assert(setSettings(session,0,baseline,2)==0 && savedSettingCount==4 && tracked(session));
    deleteSession(session);
  }
  for(unsigned condition=0;condition<3;condition++) {
    // Failed construction, disabled hooks, and foreign caller cannot enroll a session.
    constructorResult=condition==0 ? -902 : 0;
    enabled=condition==1 ? 0 : 1;
    callerImage=condition==2 ? "/Applications/App.app/App" : "/usr/lib/libnetwork.dylib";
    void *output=NULL; nextSession=session;
    int expected=constructorResult;
    int result = createSession2(&output,&callbacks,&constructorUser,&options);
    assert(result==expected && constructorKind==2);
    assert(output==session && !tracked(session));
    enabled=1; callerImage="/usr/lib/libnetwork.dylib"; constructorResult=0;
    assert(setSettings(session,0,baseline,2)==0 && savedSettingCount==2 && !tracked(session));
    assert(updateWindow(session,0,0,10485760)==17 && savedWindow==10485760);
    assert(submitRequest(session,&priorityToken,headers,6,&bodyToken,&userToken)==23 && savedPriority==&priorityToken);
  }
  for (unsigned condition=0; condition<4; condition++) {
    nextSession=session; void *output=NULL;
    assert(createSession2(&output,NULL,NULL,NULL)==0);
    SHDWH2Setting large[121]={{4,2097152}};
    SHDWH2Setting duplicate[]={{4,2097152},{4,2097152}};
    if(condition==0) allowed=0;
    if(condition==1) callerImage="/Applications/App.app/App";
    assert(setSettings(session,0,condition==2 ? large : condition==3 ? duplicate : baseline,
                       condition==2 ? 121 : 2)==0);
    allowed=1; callerImage="/usr/lib/libnetwork.dylib";
    assert(!tracked(session));
    assert(setSettings(session,0,baseline,2)==0 && savedSettingCount==2 && !tracked(session));
    deleteSession(session);
  }
  // A reused native pointer resets stale bookkeeping even if deletion was missed.
  initial(session);
  void *reused=NULL; nextSession=session;
  assert(createSession2(&reused,NULL,NULL,NULL)==0 && !tracked(session));
  assert(setSettings(session,0,baseline,2)==0 && tracked(session) && savedSettingCount==4);
  deleteSession(session);
  nextSession=NULL;
  void *nullOutput=(void *)1;
  assert(createSession2(&nullOutput,NULL,NULL,NULL)==0 && !nullOutput && !sessions);
  assert(createSession2(NULL,NULL,NULL,NULL)==0 && !sessions);
  const char *settings[]={"2:0;4:2097152;3:100","2:0;3:100;4:2097152;8:1;9:1",
                          "2:0;3:100;4:2097152;9:1","2:0;3:100;4:2097152;9:1"};
  for(unsigned profile=0;profile<4;profile++) {
    assert(SHDWH2ConfigurationParse(&configuration,settings[profile],profile ? "msap" : "mspa",
                                    profile ? 10420225 : 10485760,profile ? 256 : 255,0,profile==3));
      nextSession=session; void *output=NULL;
    assert(createSession2(&output,NULL,NULL,NULL)==0 && output==session);
    assert(setSettings(session,0,baseline,2)==0 && tracked(session));
    assert(savedSettingCount==configuration.count &&
           !memcmp(savedSettings,configuration.settings,configuration.count*sizeof(*savedSettings)));
    assert(updateWindow(session,0,0,999999)==17 && savedWindow==configuration.windowUpdate);
    assert(updateWindow(session,0,0,1234)==17 && savedWindow==1234);
    assert(submitRequest(session,&priorityToken,headers,6,&bodyToken,&userToken)==23);
    if(profile==3) assert(!savedPriority);
    else {
      assert(savedPriority && savedPriority!=nativePriority);
      const SHDWH2Priority *p=&savedPriorityValue;
      assert(p->stream==0 && p->weight==(profile ? 256 : 255) && !p->exclusive);
    }
    same(savedHeaders[0],headers[2]); same(savedHeaders[1],headers[3]);
    same(savedHeaders[2],headers[profile ? 1 : 0]); same(savedHeaders[3],headers[profile ? 0 : 1]);
    assert(submitHeaders(session,0x25,7,&priorityToken,headers,6,&userToken)==25);
    assert(savedFlags==(profile==3 ? 5 : 0x25));
    assert(profile==3 ? !savedPriority : savedPriority && savedPriority!=nativePriority);
    unsigned priorities=priorityCalls;
    assert(submitPriority(session,0,1,&priorityToken)==0 && priorityCalls==priorities);
    assert(submitPriority(session,0,7,&priorityToken)==(profile==3 ? 0 : 19));
    assert(priorityCalls==priorities+(profile!=3));
    if(profile!=3) assert(savedPriority && savedPriority!=nativePriority);
    // Trailers retain their original flags and priority argument.
    assert(submitHeaders(session,1,7,NULL,&headers[4],2,&userToken)==25);
    assert(savedHeaderPointer==&headers[4] && savedFlags==1 && !savedPriority);
    deleteSession(session);
    output=NULL;
    assert(createSession2(&output,NULL,NULL,NULL)==0);
    assert(setSettings(session,0,baseline,2)==0);
    assert(absoluteWindow(session,0,0,123456)==18 && savedWindow==65535+configuration.windowUpdate);
    assert(absoluteWindow(session,0,0,1234)==18 && savedWindow==1234);
    deleteSession(session);
  }

  // A resolver owns selection completely; an unknown/invalid client stays native.
  assert(SHDWH2ConfigurationParse(&profiles[0],"2:0;3:111;4:2222222","mspa",777777,55,1,0));
  assert(SHDWH2ConfigurationParse(&profiles[1],"2:0;3:222;4:3333333;9:1","msap",888888,99,0,1));
  assert(SHDWNativeHTTP2SetConfigurationResolver(resolveProfile));
  int connectionTokens[5];
  void *connections[5];
  for(unsigned i=0;i<5;i++) {
    connections[i]=&connectionTokens[i]; nextSession=connections[i];
    void *out=NULL;
    refuseAllocation=i==4;
    assert(createSession2(&out,&callbacks,i<3 ? &profileUsers[i] : i==4 ? &profileUsers[0] : NULL,&options)==0);
    assert(out==connections[i] && savedCallbacks==&callbacks && savedOptions==&options);
    refuseAllocation=NO;
  }
  SHDWH2Configuration expected[2]={profiles[0],profiles[1]};
  memset(profiles,0,sizeof(profiles)); // live connections own immutable copies
  for(unsigned i=0;i<5;i++) {
    assert(setSettings(connections[i],0,baseline,2)==0);
    assert(tracked(connections[i])==(i<2));
    assert(savedSettingCount==(i<2 ? expected[i].count : 2));
    if(i<2) assert(!memcmp(savedSettings,expected[i].settings,savedSettingCount*sizeof(*savedSettings)));
  }
  // Interleave operations after both SETTINGS have completed.
  for(unsigned round=0;round<2;round++) for(unsigned j=0;j<5;j++) {
    unsigned i=round ? 4-j : j;
    assert(updateWindow(connections[i],0,0,123456)==17);
    assert(savedWindow==(!round && i<2 ? expected[i].windowUpdate : 123456));
    assert(submitRequest(connections[i],nativePriority,headers,6,&bodyToken,&userToken)==23);
    if(i>=2) assert(savedHeaderPointer==headers && savedPriority==nativePriority);
    else {
      assert(savedHeaderPointer!=headers);
      same(savedHeaders[0],headers[2]); same(savedHeaders[1],headers[3]);
      same(savedHeaders[2],headers[i ? 1 : 0]); same(savedHeaders[3],headers[i ? 0 : 1]);
      if(i) assert(!savedPriority);
      else assert(savedPriority && savedPriorityValue.weight==55 && savedPriorityValue.exclusive==1);
    }
    assert(submitHeaders(connections[i],0x25,7,nativePriority,headers,6,&userToken)==25);
    assert(savedFlags==(i==1 ? 5 : 0x25));
    if(i>=2) assert(savedHeaderPointer==headers && savedPriority==nativePriority);
    unsigned previous=priorityCalls;
    assert(submitPriority(connections[i],0,7,nativePriority)==(i==1 ? 0 : 19));
    assert(priorityCalls==previous+(i!=1));
    if(i==0) assert(savedPriorityValue.weight==55 && savedPriorityValue.exclusive==1);
  }
  profiles[0]=expected[0]; profiles[1]=expected[1];
  // SETTINGS refusal on one client cannot clear another client's selected profile.
  nextSession=connections[0]; void *replacement=NULL;
  assert(createSession2(&replacement,NULL,&profileUsers[0],NULL)==0 && !tracked(connections[0]));
  settingsResult=-901;
  assert(setSettings(connections[0],0,baseline,2)==-901 && !tracked(connections[0]));
  settingsResult=0;
  assert(tracked(connections[1]));
  assert(submitRequest(connections[1],nativePriority,headers,6,NULL,NULL)==23 && !savedPriority);
  // Allocation failure on a reused pointer also discards its old profile.
  refuseAllocation=YES; nextSession=connections[1];
  assert(createSession2(&replacement,NULL,&profileUsers[0],NULL)==0 && !tracked(connections[1]));
  refuseAllocation=NO;
  assert(setSettings(connections[1],0,baseline,2)==0 && savedSettingCount==2);
  assert(submitRequest(connections[1],nativePriority,headers,6,NULL,NULL)==23);
  assert(savedHeaderPointer==headers && savedPriority==nativePriority);
  for(unsigned i=0;i<5;i++) deleteSession(connections[i]);
  assert(!sessions && resolverCalls==7);
  preparationStarted=YES;
  assert(!SHDWNativeHTTP2SetConfigurationResolver(NULL) && configurationResolver==resolveProfile);
  assert(constructorCalls);
  assert(settingCalls && windowCalls && absoluteCalls && requestCalls && headerCalls && priorityCalls);
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-native-http2-runtime-") as temporary:
    directory = Path(temporary)
    unit = directory / "runtime.m"
    binary = directory / "runtime"
    unit.write_text(setup + wrappers + tests)
    subprocess.run(["clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", "-I", str(root / "src/Transport"),
                    str(unit), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("Native HTTP/2 runtime wrapper checks passed")
