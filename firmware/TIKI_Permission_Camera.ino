/*
  TIKI PERMISSION CAMERA FIRMWARE — ESP32-S3 N16R8 + OV3660
  Arduino-ESP32 core 3.3.x / ESP32S3 Dev Module

  Retains the previously proven camera/audio GPIO configuration.

  Camera button: GPIO40 -> momentary switch -> GND
  RED LED: GPIO41 -> 330R resistor -> LED anode (+); LED cathode (-) -> GND
  Amp: GPIO14 BCLK, GPIO21 LRC, GPIO1 DIN, 5V VIN, GND GND
  Speaker: amp SPK+ and SPK-, NEVER connect to ground.

  Physical button: grants EXACTLY ONE camera capture, valid for 45 seconds.
  LED: ON ONLY during image capture/transmission; OFF during idle and voice.
  Camera /capture returns HTTP 403 without a recent physical button press.
  This is SOFTWARE-ENFORCED capture authorization, not electrical camera isolation.
  Use only on trusted local Wi-Fi (no TLS/authentication).
  Physical button press/release are reported to the Mac bridge for CAMERA ONLY; microphone is controlled separately.

  Serial: s=status, b=beep, c=permission-aware capture diagnostic (consumes grant)
  HTTP: GET /, /status, /button, /capture, /beep; POST /pcm
  Audio: 16kHz 16bit signed stereo raw PCM, multipart field 'file'
*/

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESP_I2S.h>
#include "esp_camera.h"
#include <math.h>

// Add home network credentials here; never share or commit passwords.
const char* WIFI_SSID = "";
const char* WIFI_PASSWORD = "";
const char* AP_SSID = "TIKI-TEST";
const char* AP_PASSWORD = "tiki12345";

#define AUDIO_BCLK 14
#define AUDIO_LRC  21
#define AUDIO_DIN  1
#define BUTTON_PIN 40
#define LED_PIN 41
#define AUDIO_RATE 16000

// The SAME camera pins that captured a photo in the previous working sketch.
#define CAM_XCLK 15
#define CAM_SIOD 4
#define CAM_SIOC 5
#define CAM_D0 11
#define CAM_D1 9
#define CAM_D2 8
#define CAM_D3 10
#define CAM_D4 12
#define CAM_D5 18
#define CAM_D6 17
#define CAM_D7 16
#define CAM_VSYNC 6
#define CAM_HREF 7
#define CAM_PCLK 13

const uint32_t PERMIT_MS = 45000;
const uint32_t DEBOUNCE_MS = 45;
I2SClass speaker;
WebServer server(80);
bool audioReady=false, cameraReady=false, usingAP=false;
bool lastRaw=HIGH, stableButton=HIGH, captureBusy=false;
uint32_t changedAt=0, permittedAt=0, buttonPressCount=0, buttonReleaseCount=0;
bool permitPending=false;
size_t pcmBytes=0;
uint8_t pcmTail[4]={0};
uint8_t tailLen=0;

String ipAddress(){return usingAP?WiFi.softAPIP().toString():WiFi.localIP().toString();}

bool permissionActive(){
  if(!permitPending) return false;
  // If the clock wrapped or the permit expired, the authorization is invalid.
  if((uint32_t)(millis()-permittedAt)>=PERMIT_MS) return false;
  return true;
}
void refreshLED(){digitalWrite(LED_PIN,captureBusy?HIGH:LOW);}
void pollButton(){
  bool current=digitalRead(BUTTON_PIN);
  uint32_t now=millis();
  if(current!=lastRaw){lastRaw=current;changedAt=now;}
  if(current!=stableButton&&(uint32_t)(now-changedAt)>=DEBOUNCE_MS){
    stableButton=current;
    if(current==LOW){
      buttonPressCount++;
      permittedAt=now;
      permitPending=true;
      refreshLED();
      Serial.printf("BUTTON DOWN #%lu / CAMERA GRANT (45 seconds, one photo)\n", (unsigned long)buttonPressCount);
    } else {
      buttonReleaseCount++;
      Serial.printf("BUTTON UP #%lu\n", (unsigned long)buttonReleaseCount);
    }
  }
  if(permitPending&&!permissionActive()){
    permitPending=false;
    refreshLED();
  }
}

String statusJSON(){
  String s="{";
  s+="\"chip\":\"ESP32-S3\",";
  s+="\"camera_ready\":"+String(cameraReady?"true":"false")+",";
  s+="\"audio_initialized\":"+String(audioReady?"true":"false")+",";
  s+="\"button_press_count\":"+String(buttonPressCount)+",";
  s+="\"button_release_count\":"+String(buttonReleaseCount)+",";
  s+="\"camera_armed\":"+String(permissionActive()?"true":"false")+",";
  s+="\"button_pressed\":"+String(stableButton==LOW?"true":"false")+",";
  s+="\"led_on\":"+String(captureBusy?"true":"false")+",";
  s+="\"network\":\""+String(usingAP?"hotspot":"wifi")+"\",";
  s+="\"ip\":\""+ipAddress()+"\"}";
  return s;
}
void printStatus(){
  Serial.println("\n====== TIKI STATUS ======");
  Serial.printf("Chip: %s, Flash: %u MB, PSRAM: %u MB\n",ESP.getChipModel(),(unsigned)(ESP.getFlashChipSize()/1048576),(unsigned)(ESP.getPsramSize()/1048576));
  Serial.printf("Camera: %s | Audio: %s\n",cameraReady?"READY":"FAILED",audioReady?"READY":"FAILED");
  Serial.printf("Wi-Fi: %s IP: %s\n",usingAP?"TIKI-TEST":"Home",ipAddress().c_str());
  Serial.printf("Button presses: %lu | Camera armed: %s | LED: %s\n",(unsigned long)buttonPressCount,permissionActive()?"YES":"NO",captureBusy?"ON":"OFF");
  Serial.println("=========================");
}

bool initAudio(){
  speaker.setPins(AUDIO_BCLK,AUDIO_LRC,AUDIO_DIN,-1);
  bool ok=speaker.begin(I2S_MODE_STD,AUDIO_RATE,I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_STEREO);
  Serial.println(ok?"I2S READY":"I2S FAILED");
  return ok;
}
void tone(float hz,int ms){
  if(!audioReady)return;
  const int N=192;int16_t buffer[N*2];int total=AUDIO_RATE*ms/1000;
  for(int pos=0;pos<total;pos+=N){
    int count=min(N,total-pos);
    for(int i=0;i<count;i++){
      int t=pos+i;
      float f=fminf(1.0f,fminf(t/240.0f,(total-t)/240.0f));
      int16_t v=(int16_t)(sinf(2.0f*PI*hz*t/AUDIO_RATE)*9000.0f*f);
      buffer[2*i]=v;buffer[2*i+1]=v;
    }
    speaker.write((uint8_t*)buffer,count*4);
    pollButton();
  }
}
void beep(){
  if(!audioReady){Serial.println("Audio not initialized");return;}
  tone(523.25f,200);delay(70);tone(659.25f,200);delay(70);tone(783.99f,310);
  Serial.println("TIKI tones sent");
}

bool initCamera(){
  camera_config_t cfg={};
  cfg.ledc_channel=LEDC_CHANNEL_0;cfg.ledc_timer=LEDC_TIMER_0;
  cfg.pin_d0=CAM_D0;cfg.pin_d1=CAM_D1;cfg.pin_d2=CAM_D2;cfg.pin_d3=CAM_D3;
  cfg.pin_d4=CAM_D4;cfg.pin_d5=CAM_D5;cfg.pin_d6=CAM_D6;cfg.pin_d7=CAM_D7;
  cfg.pin_xclk=CAM_XCLK;cfg.pin_pclk=CAM_PCLK;cfg.pin_vsync=CAM_VSYNC;cfg.pin_href=CAM_HREF;
  cfg.pin_sccb_sda=CAM_SIOD;cfg.pin_sccb_scl=CAM_SIOC;
  cfg.pin_pwdn=-1;cfg.pin_reset=-1;cfg.xclk_freq_hz=20000000;
  cfg.pixel_format=PIXFORMAT_JPEG;cfg.frame_size=FRAMESIZE_VGA;cfg.jpeg_quality=12;
  cfg.fb_count=1;cfg.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  cfg.fb_location=psramFound()?CAMERA_FB_IN_PSRAM:CAMERA_FB_IN_DRAM;
  esp_err_t err=esp_camera_init(&cfg);
  if(err!=ESP_OK){Serial.printf("CAMERA INIT FAILED: 0x%x\n",(unsigned)err);return false;}
  Serial.println("CAMERA READY");return true;
}

void handleCapture(){
  if(!cameraReady){server.send(503,"text/plain","Camera unavailable");return;}
  if(!permissionActive()){
    server.send(403,"text/plain","Camera locked. Press physical camera button to authorize ONE photo.");
    return;
  }
  // One permit = one attempt, even if transmission fails.
  permitPending=false;
  captureBusy=true;refreshLED();
  camera_fb_t* fb=nullptr;
  for(int attempt=0;attempt<3&&!fb;attempt++){
    fb=esp_camera_fb_get();
    if(fb && (fb->len<300 || fb->format!=PIXFORMAT_JPEG)){
      esp_camera_fb_return(fb);fb=nullptr;
    }
    if(!fb)delay(140);
  }
  if(!fb){captureBusy=false;refreshLED();server.send(500,"text/plain","Camera capture failed");return;}
  server.sendHeader("Cache-Control","no-store");
  server.setContentLength(fb->len);
  server.send(200,"image/jpeg","");
  WiFiClient client=server.client();
  size_t sent=0;uint32_t lastProgress=millis();
  while(sent<fb->len&&(uint32_t)(millis()-lastProgress)<6000){
    size_t n=min((size_t)1024,fb->len-sent);
    size_t written=client.write(fb->buf+sent,n);
    if(written){sent+=written;lastProgress=millis();}
    else if(!client.connected())break;
    pollButton();yield();
  }
  Serial.printf("IMAGE: %u/%u bytes\n",(unsigned)sent,(unsigned)fb->len);
  esp_camera_fb_return(fb);
  captureBusy=false;refreshLED();
}

void uploadPCM(){
  HTTPUpload& u=server.upload();
  if(u.status==UPLOAD_FILE_START){pcmBytes=0;tailLen=0;}
  else if(u.status==UPLOAD_FILE_WRITE&&audioReady){
    const uint8_t* p=u.buf;size_t left=u.currentSize;
    while(left&&tailLen){pcmTail[tailLen++]=*p++;left--;if(tailLen==4){pcmBytes+=speaker.write(pcmTail,4);tailLen=0;}}
    size_t aligned=left&~(size_t)3;
    if(aligned){pcmBytes+=speaker.write((uint8_t*)p,aligned);p+=aligned;left-=aligned;}
    while(left){pcmTail[tailLen++]=*p++;left--;}
    pollButton();
  }
  else if(u.status==UPLOAD_FILE_END)Serial.printf("PCM: %u bytes\n",(unsigned)pcmBytes);
}

void connectWiFi(){
  if(strlen(WIFI_SSID)){
    WiFi.mode(WIFI_STA);WiFi.setSleep(false);WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
    for(int i=0;i<48&&WiFi.status()!=WL_CONNECTED;i++){delay(250);Serial.print('.');}
    Serial.println();
  }
  if(WiFi.status()==WL_CONNECTED){usingAP=false;Serial.println("HOME WIFI CONNECTED");}
  else{usingAP=true;WiFi.mode(WIFI_AP);bool ok=WiFi.softAP(AP_SSID,AP_PASSWORD);Serial.println(ok?"TIKI-TEST HOTSPOT READY":"HOTSPOT FAILED");}
  Serial.print("Open http://");Serial.println(ipAddress());
}

const char WEB[] PROGMEM=R"HTML(
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>TIKI Device</title>
<style>body{font:16px system-ui;margin:40px auto;padding:18px;max-width:540px;background:#f6f2eb;color:#25364b}button{border:0;border-radius:9px;padding:13px;margin:6px;background:#273e54;color:white}img{max-width:100%}pre{white-space:pre-wrap}</style></head>
<body><h1>tiki. device</h1><p>Camera permission is controlled by the physical button. Red LED means the camera is currently capturing.</p>
<button onclick="fetch('/beep').then(r=>r.text()).then(alert)">Test speaker</button>
<button onclick="document.getElementById('photo').src='/capture?t='+Date.now()">Use authorized capture</button>
<pre id="status"></pre><img id="photo"><script>setInterval(()=>fetch('/status').then(r=>r.json()).then(j=>status.textContent=JSON.stringify(j,null,2)),1200)</script>
</body></html>
)HTML";

void setup(){
  Serial.begin(115200);delay(1400);
  pinMode(BUTTON_PIN,INPUT_PULLUP);pinMode(LED_PIN,OUTPUT);
  lastRaw=digitalRead(BUTTON_PIN);stableButton=lastRaw;changedAt=millis();refreshLED();
  Serial.println("\nTIKI PERMISSION CAMERA STARTING");
  audioReady=initAudio();cameraReady=initCamera();connectWiFi();
  server.on("/",HTTP_GET,[](){server.send(200,"text/html",WEB);});
  server.on("/status",HTTP_GET,[](){server.send(200,"application/json",statusJSON());});
  server.on("/button",HTTP_GET,[](){server.send(200,"application/json",statusJSON());});
  server.on("/capture",HTTP_GET,handleCapture);
  server.on("/beep",HTTP_GET,[](){if(!audioReady){server.send(503,"text/plain","Audio unavailable");return;}beep();server.send(200,"text/plain","Tones played");});
  server.on("/pcm",HTTP_POST,[](){server.send(audioReady?200:503,"text/plain",String("PCM bytes written: ")+String((unsigned)pcmBytes));},uploadPCM);
  server.onNotFound([](){server.send(404,"text/plain","Not found");});
  server.begin();printStatus();Serial.println("TIKI READY! Hold button to talk via Mac bridge. Camera capture requires a press AND spoken visual request.");
}
void loop(){
  pollButton();server.handleClient();
  if(Serial.available()){
    char c=Serial.read();
    if(c=='s')printStatus();
    if(c=='b')beep();
    if(c=='c')Serial.println("For a photo, press the physical button and open /capture in your browser.");
  }
  delay(2);
}
