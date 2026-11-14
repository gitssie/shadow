#include "../src/Transport/NativeHTTP2Policy.h"
#include <assert.h>
#include <stdio.h>

static SHDWH2Header header(const char *name, const char *value, uint8_t flags) {
  SHDWH2Header h = {(uint8_t *)name, (uint8_t *)value,
                    strlen(name), strlen(value), flags};
  return h;
}
static void same(SHDWH2Header a, SHDWH2Header b) {
  assert(a.name == b.name && a.value == b.value && a.namelen == b.namelen &&
         a.valuelen == b.valuelen && a.flags == b.flags);
}
int main(void) {
  _Static_assert(sizeof(SHDWH2Setting) == 8, "settings ABI");
#if UINTPTR_MAX == UINT64_MAX
  _Static_assert(sizeof(SHDWH2Header) == 40, "header ABI");
  _Static_assert(offsetof(SHDWH2Header, flags) == 32, "header flags ABI");
#endif
  SHDWH2Setting baseline[] = {{4,2097152},{3,100}}, settings[132];
  assert(SHDWH2Settings(baseline,2,settings,132) == 4);
  assert(settings[0].id == 2 && settings[0].value == 0);
  assert(settings[1].id == 3 && settings[1].value == 100);
  assert(settings[2].id == 4 && settings[2].value == 2097152);
  assert(settings[3].id == 9 && settings[3].value == 1);
  assert(baseline[0].id == 4 && baseline[1].id == 3);
  SHDWH2Setting extras[] = {{10,8},{4,65535},{1,8192},{9,0},{2,1},{3,4},{8,1}};
  assert(SHDWH2Settings(extras,7,settings,132) == 7);
  assert(settings[4].id == 10 && settings[4].value == 8);
  assert(settings[5].id == 1 && settings[6].id == 8);
  SHDWH2Setting duplicates[] = {{4,1},{4,2}};
  assert(!SHDWH2Settings(duplicates,2,settings,132));
  duplicates[0].id = duplicates[1].id = 42;
  assert(!SHDWH2Settings(duplicates,2,settings,132));
  assert(!SHDWH2Settings(baseline,2,settings,3));
  assert(!SHDWH2Settings(NULL,1,settings,132));
  assert(!SHDWH2Settings(baseline,129,settings,132));
  assert(!SHDWH2Settings(baseline,2,baseline,2));
  SHDWH2Setting invalid[] = {{2,2},{9,2},{4,UINT32_MAX},{5,1},{-1,0},{65536,0}};
  for (size_t i=0;i<sizeof(invalid)/sizeof(*invalid);++i)
    assert(!SHDWH2Settings(&invalid[i],1,settings,132));
  assert(SHDWH2Settings(NULL,0,settings,132) == 4);
  SHDWH2Setting unknownZero = {0,123};
  assert(SHDWH2Settings(&unknownZero,1,settings,132) == 5);
  assert(settings[4].id == 0 && settings[4].value == 123);

  SHDWH2Header headers[] = {
    header(":path","/",6), header(":authority","example.test",2),
    header(":method","POST",4), header(":scheme","https",0),
    header(":protocol","websocket",6), header("cookie","a=1",6),
    header("cookie","b=2",2), header("x-test","value",0)
  }, out[8], before[8];
  memcpy(before,headers,sizeof(headers));
  assert(SHDWH2Headers(headers,8,out,8) == 8);
  size_t expected[] = {2,3,1,0,4,5,6,7};
  for (size_t i=0;i<8;++i) { same(out[i],headers[expected[i]]); same(headers[i],before[i]); }
  assert(!SHDWH2Headers(headers,8,out,7));
  assert(!SHDWH2Headers(headers,1025,out,8));
  assert(!SHDWH2Headers(headers,8,headers,8));
  assert(!SHDWH2Headers(&headers[5],3,out,8)); /* trailers */
  SHDWH2Header bad[] = {header(":method","GET",0),header("x","y",0),header(":path","/",0)};
  assert(!SHDWH2Headers(bad,3,out,8));
  bad[1]=bad[0];
  assert(!SHDWH2Headers(bad,3,out,8));
  bad[1]=header(":","",0);
  assert(!SHDWH2Headers(bad,2,out,8));
  bad[1]=header("","",0);
  assert(!SHDWH2Headers(bad,2,out,8));
  bad[1]=header("x","y",0); bad[1].value=NULL;
  assert(!SHDWH2Headers(bad,2,out,8));
  assert(!SHDWH2Headers(NULL,0,out,8));
  SHDWH2Header connect[] = {header(":authority","example.test:443",6),header(":method","CONNECT",0)};
  assert(SHDWH2Headers(connect,2,out,8) == 2);
  same(out[0],connect[1]); same(out[1],connect[0]);
  /* Deliberately unterminated field names exercise length-based matching. */
  uint8_t method[] = {':','m','e','t','h','o','d'};
  connect[1].name=method; connect[1].namelen=sizeof(method);
  assert(SHDWH2Headers(connect,2,out,8) == 2);
  same(out[0],connect[1]);
  puts("Native HTTP/2 policy checks passed");
  return 0;
}
