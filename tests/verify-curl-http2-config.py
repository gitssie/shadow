"""Exercise the production curl configuration export and native snapshot reader."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
patch = (root / "build-support/patches/curl-connect-only-raw-http2.patch").read_text()
start = patch.index("+CURL_EXTERN CURLcode curl_shadow_get_http2_config(")
end = patch.index("+CURL_EXTERN CURLcode curl_shadow_connect_only_enable_external_io", start)
getter = "\n".join(line[1:] for line in patch[start:end].splitlines() if line.startswith("+"))
header = r'''
#pragma once
#include <stddef.h>
typedef struct Curl_easy CURL;
struct curl_slist;
typedef int CURLcode;
typedef int CURLoption;
#define CURL_EXTERN
#define CURLE_OK 0
#define CURLE_BAD_FUNCTION_ARGUMENT 43
#define CURLE_NOT_BUILT_IN 4
#define CURLE_UNKNOWN_OPTION 48
#define CURL_SSLVERSION_TLSv1_2 6
#define CURL_SSLVERSION_MAX_TLSv1_3 (7 << 16)
enum {
  CURLOPT_HTTPBASEHEADER=10000, CURLOPT_USERAGENT, CURLOPT_SSL_CIPHER_LIST,
  CURLOPT_SSL_EC_CURVES, CURLOPT_SSL_SIG_HASH_ALGS, CURLOPT_TLS_EXTENSION_ORDER,
  CURLOPT_SSL_CERT_COMPRESSION, CURLOPT_HTTP2_SETTINGS,
  CURLOPT_HTTP2_PSEUDO_HEADERS_ORDER,
  CURLOPT_TLS_KEY_SHARES_LIMIT=1, CURLOPT_SSLVERSION,
  CURLOPT_SSL_PERMUTE_EXTENSIONS, CURLOPT_TLS_GREASE,
  CURLOPT_SSL_ENABLE_TICKET, CURLOPT_HTTP2_WINDOW_UPDATE,
  CURLOPT_HTTP2_NO_PRIORITY
};
'''
setup = r'''
#include <assert.h>
#include <limits.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <curl/curl.h>
#define STRING_HTTP2_SETTINGS 0
#define STRING_HTTP2_PSEUDO_HEADERS_ORDER 1
#define STRING_HTTP2_STREAMS 2
struct Curl_easy {
  void *multi,*conn;
  struct {
    const char *strings[3];
    int http2_window_update,weight,stream_exclusive,http2_no_priority;
  } set;
  unsigned profiles,options;
  const char *base;
};
#define CURL_EASY_STR(data,id) ((data)->set.strings[id])
#include "CurlHTTP2.h"
#include "CurlReference.h"
'''
tests = r'''
static const struct {
  const char *name,*settings,*order;
  long window,weight,noPriority;
} profiles[] = {
  {"safari172_ios","2:0;4:2097152;3:100","mspa",10485760,255,0},
  {"safari180_ios","2:0;3:100;4:2097152;8:1;9:1","msap",10420225,256,0},
  {"safari184_ios","2:0;3:100;4:2097152;9:1","msap",10420225,256,0},
  {"safari187_ios","2:0;3:100;4:2097152;9:1","msap",10420225,256,1}
};
static CURLcode impersonate(CURL *e,const char *profile,int defaultHeaders) {
  assert(e && defaultHeaders==0);
  e->profiles++;e->base=profile;
  for(size_t i=0;i<3;i++) if(!strcmp(profile,profiles[i].name)) {
    e->set.strings[0]=profiles[i].settings;
    e->set.strings[1]=profiles[i].order;
    e->set.http2_window_update=(int)profiles[i].window;
    e->set.weight=(int)profiles[i].weight;
    return CURLE_OK;
  }
  return CURLE_BAD_FUNCTION_ARGUMENT;
}
static CURLcode set(CURL *e,CURLoption option,...) {
  e->options++;
  va_list args;va_start(args,option);
  switch(option) {
    case CURLOPT_HTTPBASEHEADER: assert(!va_arg(args,struct curl_slist *));break;
    case CURLOPT_USERAGENT: assert(!va_arg(args,char *));break;
    case CURLOPT_HTTP2_SETTINGS: e->set.strings[0]=va_arg(args,const char *);break;
    case CURLOPT_HTTP2_PSEUDO_HEADERS_ORDER: e->set.strings[1]=va_arg(args,const char *);break;
    case CURLOPT_HTTP2_WINDOW_UPDATE: e->set.http2_window_update=(int)va_arg(args,long);break;
    case CURLOPT_HTTP2_NO_PRIORITY: e->set.http2_no_priority=(int)va_arg(args,long);break;
    case CURLOPT_TLS_KEY_SHARES_LIMIT: case CURLOPT_SSLVERSION:
    case CURLOPT_SSL_PERMUTE_EXTENSIONS: case CURLOPT_TLS_GREASE:
    case CURLOPT_SSL_ENABLE_TICKET: (void)va_arg(args,long);break;
    case CURLOPT_SSL_CIPHER_LIST: case CURLOPT_SSL_EC_CURVES:
    case CURLOPT_SSL_SIG_HASH_ALGS: case CURLOPT_TLS_EXTENSION_ORDER:
    case CURLOPT_SSL_CERT_COMPRESSION: assert(va_arg(args,const char *));break;
    default: abort();
  }
  va_end(args);return CURLE_OK;
}
static void unchanged(const SHDWH2Configuration *config) {
  const unsigned char *bytes=(const unsigned char *)config;
  for(size_t i=0;i<sizeof(*config);i++) assert(bytes[i]==0xa5);
}
static int malformedMode;
static CURLcode malformed(CURL *e,char *settings,size_t settingsCapacity,
    char *order,size_t orderCapacity,long *window,long *weight,long *exclusive,long *noPriority) {
  CURLcode result=curl_shadow_get_http2_config(e,settings,settingsCapacity,
      order,orderCapacity,window,weight,exclusive,noPriority);
  assert(result==CURLE_OK);
  switch(malformedMode) {
    case 0: return CURLE_UNKNOWN_OPTION;
    case 1: memset(settings,'1',settingsCapacity);break;
    case 2: memset(order,'m',orderCapacity);break;
    case 3: strcpy(settings,"4:1;4:2");break;
    case 4: strcpy(order,"mmsp");break;
    case 5: strcpy(settings,"2:2");break;
    case 6: strcpy(settings,"4:2147483648");break;
    case 7: strcpy(settings,"65536:1");break;
    case 8: strcpy(settings,"1:4294967296");break;
    case 9: strcpy(settings,"4:1;");break;
    case 10: strcpy(settings,"");break;
    case 11: *window=LONG_MAX;break;
    case 12: *weight=257;break;
    case 13: *exclusive=-1;break;
    case 14: *noPriority=2;break;
    default: abort();
  }
  return CURLE_OK;
}
static void rejectionChecks(CURL *e) {
  char settings[128],order[5];
  long window,weight,exclusive,noPriority;
#define RESET() do { strcpy(settings,"unchanged");strcpy(order,"same");window=11;weight=12;exclusive=13;noPriority=14; } while(0)
#define UNCHANGED() do { assert(!strcmp(settings,"unchanged") && !strcmp(order,"same"));assert(window==11 && weight==12 && exclusive==13 && noPriority==14); } while(0)
#define GET(c,s,sc,o,oc,w,wt,x,n) curl_shadow_get_http2_config(c,s,sc,o,oc,w,wt,x,n)
  RESET();
  assert(GET(e,settings,1,order,sizeof(order),&window,&weight,&exclusive,&noPriority)==CURLE_BAD_FUNCTION_ARGUMENT);UNCHANGED();
  assert(GET(e,settings,sizeof(settings),order,4,&window,&weight,&exclusive,&noPriority)==CURLE_BAD_FUNCTION_ARGUMENT);UNCHANGED();
  for(unsigned field=0;field<7;field++) {
    assert(GET(field==0?NULL:e,field==1?NULL:settings,sizeof(settings),field==2?NULL:order,sizeof(order),
        field==3?NULL:&window,field==4?NULL:&weight,field==5?NULL:&exclusive,field==6?NULL:&noPriority)==CURLE_BAD_FUNCTION_ARGUMENT);
    UNCHANGED();
  }
  e->multi=(void *)1;
  assert(GET(e,settings,sizeof(settings),order,sizeof(order),&window,&weight,&exclusive,&noPriority)==CURLE_BAD_FUNCTION_ARGUMENT);UNCHANGED();
  e->multi=NULL;e->conn=(void *)1;
  assert(GET(e,settings,sizeof(settings),order,sizeof(order),&window,&weight,&exclusive,&noPriority)==CURLE_BAD_FUNCTION_ARGUMENT);UNCHANGED();
  e->conn=NULL;e->set.strings[2]="1:0:0:256";
  assert(GET(e,settings,sizeof(settings),order,sizeof(order),&window,&weight,&exclusive,&noPriority)==CURLE_NOT_BUILT_IN);UNCHANGED();
  e->set.strings[2]=NULL;
  for(unsigned field=0;field<2;field++) {
    const char *saved=e->set.strings[field];e->set.strings[field]=NULL;
    assert(GET(e,settings,sizeof(settings),order,sizeof(order),&window,&weight,&exclusive,&noPriority)==CURLE_BAD_FUNCTION_ARGUMENT);UNCHANGED();
    e->set.strings[field]="";
    assert(GET(e,settings,sizeof(settings),order,sizeof(order),&window,&weight,&exclusive,&noPriority)==CURLE_BAD_FUNCTION_ARGUMENT);UNCHANGED();
    e->set.strings[field]=saved;
  }
  SHDWH2Configuration config;memset(&config,0xa5,sizeof(config));
  assert(SHDWCurlReadHTTP2Configuration(NULL,curl_shadow_get_http2_config,&config)==CURLE_BAD_FUNCTION_ARGUMENT);unchanged(&config);
  assert(SHDWCurlReadHTTP2Configuration(e,NULL,&config)==CURLE_BAD_FUNCTION_ARGUMENT);unchanged(&config);
  assert(SHDWCurlReadHTTP2Configuration(e,curl_shadow_get_http2_config,NULL)==CURLE_BAD_FUNCTION_ARGUMENT);
  for(malformedMode=0;malformedMode<15;malformedMode++) {
    assert(SHDWCurlReadHTTP2Configuration(e,malformed,&config)==(malformedMode==0?CURLE_UNKNOWN_OPTION:CURLE_BAD_FUNCTION_ARGUMENT));
    unchanged(&config);
  }
}
int main(void) {
#ifdef USE_HTTP2
  for(size_t i=0;i<sizeof(profiles)/sizeof(*profiles);i++) {
    CURL e={0};
    assert(SHDWCurlApplyProfile(&e,profiles[i].name,impersonate,set)==CURLE_OK);
    assert(e.profiles==1 && e.options==(i==3?16u:2u));
    assert(!strcmp(e.base,profiles[i==3?2:i].name));
    SHDWH2Configuration snapshot;
    assert(SHDWCurlReadHTTP2Configuration(&e,curl_shadow_get_http2_config,&snapshot)==CURLE_OK);
    assert(snapshot.windowUpdate==profiles[i].window && snapshot.weight==profiles[i].weight);
    assert(snapshot.noPriority==profiles[i].noPriority && !snapshot.exclusive);
    assert(!strcmp(snapshot.order,profiles[i].order));
    SHDWH2Configuration expected;
    assert(SHDWH2ConfigurationParse(&expected,profiles[i].settings,profiles[i].order,
        profiles[i].window,profiles[i].weight,0,profiles[i].noPriority));
    assert(snapshot.count==expected.count && !memcmp(snapshot.settings,expected.settings,snapshot.count*sizeof(snapshot.settings[0])));
    e.set.strings[0]="2:0";e.set.strings[1]="masp";
    assert(!strcmp(snapshot.order,profiles[i].order) && snapshot.count==expected.count);
  }
  CURL e={0};assert(SHDWCurlApplyProfile(&e,"safari187_ios",impersonate,set)==CURLE_OK);
  rejectionChecks(&e);
  e.set.http2_window_update=0;e.set.weight=0;
  SHDWH2Configuration defaults;
  assert(SHDWCurlReadHTTP2Configuration(&e,curl_shadow_get_http2_config,&defaults)==CURLE_OK);
  assert(defaults.windowUpdate==15663105 && defaults.weight==256);
#else
  CURL e={0};SHDWH2Configuration snapshot;memset(&snapshot,0xa5,sizeof(snapshot));
  assert(SHDWCurlReadHTTP2Configuration(&e,curl_shadow_get_http2_config,&snapshot)==CURLE_NOT_BUILT_IN);
  unchanged(&snapshot);
  (void)impersonate;(void)set;(void)rejectionChecks;
#endif
  puts("curl HTTP/2 configuration export and snapshot checks passed");
}
'''
with tempfile.TemporaryDirectory(prefix="shadow-curl-http2-config-") as temporary:
    directory = Path(temporary)
    (directory / "curl").mkdir()
    (directory / "curl/curl.h").write_text(header)
    unit, binary = directory / "test.c", directory / "test"
    unit.write_text(setup + getter + tests)
    for enabled in (False, True):
        command = [os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=address,undefined", "-I", str(directory),
                   "-I", str(root / "src/Transport"), str(unit), "-o", str(binary)]
        if enabled:
            command.append("-DUSE_HTTP2")
        subprocess.run(command, check=True)
        subprocess.run([str(binary)], check=True)
