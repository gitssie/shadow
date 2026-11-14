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
#include "NativeHTTP2Policy.h"
#undef ptrauth_strip
#undef ptrauth_sign_unauthenticated
#define ptrauth_strip(p,k) (p)
#define ptrauth_sign_unauthenticated(p,k,d) (p)
static const char *callerImage;
static int mockDladdr(const void *pc, Dl_info *image) {
  (void)pc; image->dli_fname=callerImage; return callerImage != NULL;
}
#define dladdr mockDladdr
static void SHDWCurlTrace(NSString *stage,id request,NSDictionary *details) {
  (void)stage; (void)request; (void)details;
}
'''
tests = r'''
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
static const void *savedPriority,*savedBody;
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
  savedSession=session; savedPriority=priority; savedUser=user; savedHeaderCount=count;
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
  originals[0]=(void *)originalSettings; originals[1]=(void *)originalWindow;
  originals[2]=(void *)originalAbsolute; originals[3]=(void *)originalRequest;
  originals[4]=(void *)originalHeaders; originals[5]=(void *)originalPriority; originals[6]=(void *)originalDelete;
  originals[7]=(void *)originalNew2;
  clientAllowed=allowClient;
  int sessionToken=0,unknownToken=0,priorityToken=0,bodyToken=0,userToken=0;
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
                    "-framework", "Foundation", "-I", str(root / "src/Transport"),
                    str(unit), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("Native HTTP/2 runtime wrapper checks passed")
