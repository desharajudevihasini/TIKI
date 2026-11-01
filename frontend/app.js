'use strict';
/* No chatbot UI. The app mirrors the native Mac bridge and offers a manual mic fallback. */
const $=id=>document.getElementById(id);
const ui={busy:false,recording:false,rec:null,stream:null,chunks:[],library:'reminders',seenHeard:'',seenAnswer:'',lastState:'',wake:false,cameraBusy:false,cameraPollAt:0,lastProposal:'',quickRecognizer:null,quickTranscript:'',quickRecogError:false};
const stateNames={disconnected:'TIKI is offline', 'firmware-error':'Update ESP32 button firmware',starting:'Starting',ready:'Ready',listening:'Listening…',transcribing:'Transcribing…',thinking:'Thinking…',looking:'Looking…',speaking:'Speaking through TIKI…',awake:'Spots on. I’m here.',error:'Connection issue', 'speaker-error':'Speaker not connected', 'camera-error':'Camera button problem','mic-error':'Mac microphone unavailable'};
function status(label,mode='ready'){$('status').textContent=label;$('character').dataset.mode=mode;}
function showAnswer(text){$('answer').textContent=text||'';}
function setHeard(text){$('heard').textContent=text||'';$('correctTranscript').hidden=!text;}
function showPhoto(url){if(!url)return;const img=$('lastPhoto');if(img.getAttribute('data-url')===url)return;img.setAttribute('data-url',url);img.src=url;img.hidden=false;}
function showProposal(p){
 const tasks=p&&Array.isArray(p.tasks)?p.tasks:[];
 $('proposal').hidden=!tasks.length;
 $('proposalItems').replaceChildren();
 for(const t of tasks){const line=document.createElement('div');line.textContent='• '+t.task+(t.due_text?' — due as written: '+t.due_text:'');$('proposalItems').append(line);}
}
async function json(url,method='GET',body){
 const opts={method,cache:'no-store'};
 if(body!==undefined){opts.headers={'Content-Type':'application/json'};opts.body=JSON.stringify(body);}
 const r=await fetch(url,opts);const data=await r.json().catch(()=>({}));
 if(!r.ok)throw Error(data.detail||data.message||('HTTP '+r.status));return data;
}
let updateInFlight=false;
async function update(){
 if(updateInFlight)return;
 updateInFlight=true;
 try{
  const s=await json('/api/bridge/state');
  if(!ui.busy){
   if(s.state!==ui.lastState||s.detail!=$('status').textContent){status(s.detail||stateNames[s.state]||'Ready',s.state);ui.lastState=s.state;}
   if(s.heard&&s.heard!==ui.seenHeard){setHeard(s.heard);ui.seenHeard=s.heard;}
   if(s.answer&&s.answer!==ui.seenAnswer){showAnswer(s.answer);ui.seenAnswer=s.answer;}
   if(s.photo_url)showPhoto(s.photo_url);
  }
  const connected=!!s.glasses_connected;
  $('deviceLabel').textContent=connected?'TIKI glasses connected':'Waiting for TIKI glasses';
  document.querySelector('footer').classList.toggle('connected',connected);
  if(!ui.busy){
   $('help').textContent=['error','speaker-error','firmware-error','disconnected','camera-error','mic-error'].includes(s.state)?(s.error||s.detail):
    !s.bridge_running?'Mac bridge off. Enable TIKI_MAC_BRIDGE=1 in .env.':
    !connected?'ESP32 not reachable. Check its IP in Serial Monitor and update TIKI_ESP_URL in .env.':
    !s.wake_model_installed&&s.wake_enabled?'Physical button takes pictures. Talk on screen, or install the optional wake model.':
    'Use Talk to speak. The physical glasses button takes pictures.';
  }
  const toggle=$('wakeToggle');
  if(document.activeElement!==toggle)toggle.checked=!!s.wake_enabled;
  toggle.title=s.wake_model_installed?'Offline wake phrase available':'Install local Vosk model for hands-free wake recognition';
  // If a manual voice request was waiting for camera permission, a later
  // physical press will complete it automatically. One grant = one photo.
  if(!ui.cameraBusy && !ui.busy && Date.now()>ui.cameraPollAt){
   // The native bridge already polls /button frequently. Avoid flooding
   // the single-threaded ESP32 by asking /api/state every 1.1 seconds.
   ui.cameraPollAt=Date.now()+(s.bridge_running?15000:4500);
   const backend=await json('/api/state');
   const pending=backend.pending_camera;
   showProposal(backend.proposed_tasks);
   if(!s.photo_url && backend.last_photo?.filename)showPhoto('/api/photos/'+backend.last_photo.filename);
   if(pending && !s.bridge_running && backend.device?.camera_armed &&
      Number(backend.device.button_press_count)>Number(pending.after_press)){
     ui.cameraBusy=true;
     status('Looking…','looking');
     try{
       const photo=await json('/api/camera/complete','POST');
       showAnswer(photo.reply);ui.seenAnswer=photo.reply;showPhoto(photo.photo_url);
       status('Speaking through TIKI…','speaking');
       const out=await json('/api/speak','POST',{text:(photo.spoken_reply||photo.reply).slice(0,240)});
       if(out.target!=='tiki')throw Error(out.reason||'Glasses speaker unavailable');
       status('Ready for you.','ready');
     }catch(err){showAnswer('Camera interrupted: '+err.message);status('Camera unavailable.','error');}
     finally{ui.cameraBusy=false;}
   }
  }
 }catch(e){status('Start TIKI from VS Code.','error');$('help').textContent=String(e.message||e);}
 finally{updateInFlight=false;}
}
async function presentChat(r,elapsed=''){
 if(r.kind==='camera_permission'){
  showAnswer('Press TIKI’s physical camera button once to save and describe a photo.');
  status('Waiting for camera button…','looking');
  return;
 }
 showAnswer(r.reply||'');
 status('Answer ready'+(elapsed?' · '+elapsed+'s':'')+' · speaking through TIKI…','speaking');
 const spoken=(r.spoken_reply||r.reply||'').slice(0,125);
 if(!spoken){status('Ready.','ready');return;}
 const out=await json('/api/speak','POST',{text:spoken});
 if(out.target!=='tiki')throw Error('TIKI speaker unavailable: '+out.reason);
 status('Ready for you.','ready');
}
async function processText(text){
 if(!text.trim())return;
 ui.busy=true;$('talkBtn').disabled=true;
 setHeard(text);status('Thinking…','thinking');
 try{
  const start=performance.now();
  const r=await json('/api/chat','POST',{text:text.trim()});
  await presentChat(r,((performance.now()-start)/1000).toFixed(1));
 }catch(e){showAnswer('I could not finish: '+(e.message||e));status('Check the connection.','error');}
 finally{ui.busy=false;$('talkBtn').disabled=false;}
}
function stopRecording(){
 if(!ui.rec||ui.rec.state!=='recording')return;
 ui.rec.stop();ui.recording=false;$('talkText').textContent='Talk to TIKI';$('talkBtn').classList.remove('recording');
}
async function startRecording(){
 if(ui.busy)return;
 if(ui.recording){stopRecording();return;}
 if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder){status('Open on localhost in Chrome and allow the microphone.','error');return;}
 try{
  // The app records ONLY after you click Talk. The physical glasses button is camera-only.
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
  ui.stream=stream;ui.chunks=[];
  ui.quickRecognizer=null;ui.quickTranscript='';ui.quickRecogError=false;ui.quickRecogEnded=false;
  // Web Speech is a faster optional path for the ON-SCREEN Talk button.
  // If unavailable or inaccurate, edit the displayed transcript, or disable
  // this optimization with TIKI_FAST_BROWSER_SPEECH in localStorage.
  const QuickSpeech=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(QuickSpeech && localStorage.getItem('TIKI_FAST_BROWSER_SPEECH')!=='0'){
   try{
    const recognition=new QuickSpeech();
    recognition.lang='en-US';recognition.continuous=true;
    recognition.interimResults=false;recognition.maxAlternatives=1;
    recognition.onresult=event=>{
     const words=[];
     for(let i=0;i<event.results.length;i++){
      if(event.results[i].isFinal)words.push(event.results[i][0].transcript);
     }
     ui.quickTranscript=words.join(' ').trim();
    };
    recognition.onerror=()=>{ui.quickRecogError=true;};
    recognition.onend=()=>{ui.quickRecogEnded=true;};
    recognition.start();ui.quickRecognizer=recognition;
   }catch(e){ui.quickRecognizer=null;}
  }
  const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg'].find(t=>MediaRecorder.isTypeSupported(t));
  const rec=mime?new MediaRecorder(stream,{mimeType:mime}):new MediaRecorder(stream);
  ui.rec=rec;
  rec.ondataavailable=e=>{if(e.data.size)ui.chunks.push(e.data);};
  rec.onstop=async()=>{
   stream.getTracks().forEach(t=>t.stop());ui.stream=null;
   const blob=new Blob(ui.chunks,{type:rec.mimeType||'audio/webm'});
   ui.chunks=[];
   // Chrome speech recognition is OPTIONAL and runs in parallel with the
   // recorder, saving a full Gemini round trip when it returns a final result.
   // Recorded audio is retained as the fallback; camera-only hardware is untouched.
   const quick=ui.quickRecognizer;
   if(quick){
    await new Promise(resolve=>{
     let done=false;
     const finish=()=>{if(!done){done=true;resolve();}};
     if(ui.quickRecogEnded){finish();return;}
     quick.addEventListener('end',finish,{once:true});
     try{quick.stop();}catch(e){finish();}
     setTimeout(finish,550);
    });
   }
   ui.quickRecognizer=null;
   const fastText=(!ui.quickRecogError && ui.quickTranscript && ui.quickTranscript.length>=6)
     ?ui.quickTranscript.trim():'';
   if(!blob.size && !fastText){status('Nothing recorded.','ready');return;}
   ui.busy=true;
   try{
    if(fastText){
     status('Got it — responding…','thinking');
     ui.busy=false;await processText(fastText);return;
    }
    status('Understanding & answering…','transcribing');
    const f=new FormData();f.append('file',blob,blob.type.includes('mp4')?'voice.m4a':'voice.webm');
    const voiceStart=performance.now();
    let response, data;
    try{
     response=await fetch('/api/voice/fast',{method:'POST',body:f});
     data=await response.json();
     if(!response.ok)throw Error(data.detail||'Fast voice processing failed');
     setHeard(data.text);ui.seenHeard=data.text;
     await presentChat(data,((performance.now()-voiceStart)/1000).toFixed(1));
    }catch(fastError){
     // Fail safely on models that cannot produce JSON: use the proven old
     // transcription path, never pretend the audio was understood.
     status('Fast voice unavailable — trying standard transcription…','transcribing');
     const fallback=await fetch('/api/transcribe',{method:'POST',body:f});
     const recovered=await fallback.json();
     if(!fallback.ok)throw Error('Fast: '+(fastError.message||fastError)+'; fallback: '+(recovered.detail||'Transcription failed'));
     ui.busy=false;
     await processText(recovered.text);
    }
   }catch(e){showAnswer('I could not hear you: '+(e.message||e));status('Try again.','error');}
   finally{ui.busy=false;}
  };
  rec.start();ui.recording=true;$('talkText').textContent='Finish speaking';$('talkBtn').classList.add('recording');status('Listening…','listening');
 }catch(e){status('Microphone unavailable.','error');$('help').textContent='Allow microphone access in your Mac privacy settings: '+e.message;}
}
let drawerOpen=false;
function closeDrawer(){$('drawer').hidden=true;drawerOpen=false;}
function itemText(element,cls,content){const x=document.createElement(element);if(cls)x.className=cls;x.textContent=content||'';return x;}
function photoCard(x){
 const item=document.createElement('article');item.className='item photo-item';
 const img=document.createElement('img');img.src=x.photo_url||('/api/photos/'+x.filename);img.className='photo-thumb';img.alt='Saved photo';img.loading='lazy';
 img.onclick=()=>{showPhoto(img.src);closeDrawer();};
 const body=document.createElement('div');
 body.append(itemText('strong','',x.request_text||'Captured photo'));
 body.append(itemText('div','meta',x.created_at||''));
 body.append(itemText('p','',x.analysis||''));
 const del=itemText('button','delete','×');del.type='button';del.title='Delete this photo';
 del.onclick=async()=>{if(confirm('Delete this photo? The associated note text will remain.')){await json('/api/captures/'+x.id,'DELETE');fillLibrary();}};
 item.append(img,body,del);return item;
}
function genericCard(x,category){
 const item=document.createElement('article');item.className='item';
 const title=itemText('strong','',x.title||x.content||'Saved');
 const detail=itemText('p','',x.content&&x.title?x.content:(x.due_at?'Due: '+new Date(x.due_at).toLocaleString():'') );
 const del=itemText('button','','×');del.type='button';del.title='Delete';
 del.onclick=async()=>{if(confirm('Delete this item?')){await json('/api/'+category+'/'+x.id,'DELETE');fillLibrary();}};
 item.append(title,detail,del);return item;
}
async function fillLibrary(){
 const box=$('items');box.replaceChildren();
 const category=ui.library;
 $('saveForm').hidden=category==='captures';$('dueWrap').hidden=category!=='reminders';
 try{
  const items=await json('/api/'+category);
  if(!items.length){box.textContent=category==='captures'?'Photos taken with TIKI will appear here.':'Nothing saved yet.';return;}
  for(const x of items)box.append(category==='captures'?photoCard(x):genericCard(x,category));
 }catch(e){box.textContent='Could not load: '+e.message;}
}
$('talkBtn').addEventListener('click',startRecording);
$('typeForm').addEventListener('submit',e=>{e.preventDefault();const input=$('typeText');const text=input.value;input.value='';processText(text);});
$('wakeToggle').addEventListener('change',async e=>{
 try{const s=await json('/api/bridge/wake','POST',{enabled:e.target.checked});
  if(e.target.checked&&!s.wake_model_installed){$('help').textContent='For hands-free speech, run python tools/install_wake_model.py. The physical button is for photos only.';}
 }catch(err){$('help').textContent=err.message;}
});
$('worldBtn').onclick=()=>{$('drawer').hidden=false;drawerOpen=true;fillLibrary();};
$('closeDrawer').onclick=closeDrawer;
$('drawer').onclick=e=>{if(e.target===$('drawer'))closeDrawer();};
document.querySelectorAll('[data-category]').forEach(b=>b.onclick=()=>{ui.library=b.dataset.category;document.querySelectorAll('[data-category]').forEach(x=>x.classList.toggle('on',x===b));$('saveText').placeholder=ui.library==='memories'?'What should TIKI remember?':ui.library==='notes'?'Save a note':'Add a plan';fillLibrary();});
$('saveForm').onsubmit=async e=>{e.preventDefault();const input=$('saveText');const content=input.value.trim();if(!content)return;let path='/api/'+ui.library;let body=ui.library==='memories'?{content}:ui.library==='notes'?{title:'Quick note',content}:{title:content};try{await json(path,'POST',body);input.value='';$('dueInput').value='';fillLibrary();}catch(err){alert(err.message);}};
$('testSpeaker').onclick=async()=>{try{await json('/api/device/chime','POST');$('testSpeaker').textContent='Tones sent to the glasses';}catch(e){$('testSpeaker').textContent='Speaker not connected: '+e.message;}};
update();setInterval(update,900);

$('correctTranscript').onclick=()=>{
 $('typeText').value=$('heard').textContent;
 document.querySelector('details.fallback').open=true;
 $('typeText').focus();
};
$('approveTasks').onclick=async()=>{try{const r=await json('/api/proposed-tasks/decide','POST',{approve:true});showProposal(null);showAnswer(r.count?'Saved '+r.count+' tasks to your plans.':'No pending tasks.');}catch(e){showAnswer(e.message);}};
$('rejectTasks').onclick=async()=>{try{await json('/api/proposed-tasks/decide','POST',{approve:false});showProposal(null);}catch(e){showAnswer(e.message);}};
$('exportBackup').onclick=()=>{window.location.href='/api/backup';};
$('searchForm').onsubmit=async e=>{
 e.preventDefault();const q=$('searchText').value.trim();if(!q){fillLibrary();return;}
 const box=$('items');box.textContent='Searching…';
 try{
  const items=await json('/api/search?q='+encodeURIComponent(q));box.replaceChildren();
  if(!items.length){box.textContent='No saved results for “'+q+'”.';return;}
  for(const x of items){
   if(x.photo_url && x.kind==='photo'){box.append(photoCard({...x,request_text:x.title,analysis:x.excerpt,filename:x.photo_url.split('/').pop(),photo_url:x.photo_url}));continue;}
   const item=document.createElement('article');item.className='item';item.append(itemText('strong','',x.label+' · '+x.title),itemText('p','',x.excerpt));box.append(item);
  }
 }catch(err){box.textContent=err.message;}
};
$('takePhonePhoto').onclick=()=>$('phonePhoto').click();
$('phonePhoto').onchange=async e=>{
 const file=e.target.files?.[0];if(!file)return;
 const promptText=prompt('What should TIKI describe or remember from this photo?','Describe this picture and remember what you can see.');
 if(!promptText?.trim()){e.target.value='';return;}
 closeDrawer();ui.busy=true;status('Looking at your photo…','looking');
 try{
  const data=new FormData();data.append('file',file,file.name);data.append('text',promptText.trim());
  const resp=await fetch('/api/phone/photo',{method:'POST',body:data});const result=await resp.json();
  if(!resp.ok)throw Error(result.detail||'Photo upload failed');
  showPhoto(result.photo_url);showAnswer(result.reply);showProposal(result.proposed_tasks);
  const out=await json('/api/speak','POST',{text:(result.spoken_reply||result.reply).slice(0,240)});
  if(out.target!=='tiki')throw Error('Photo saved, but glasses speaker failed: '+out.reason);
  status('Photo saved. Ready.','ready');
 }catch(err){showAnswer('Photo interrupted: '+err.message);status('Check your connection.','error');}
 finally{ui.busy=false;e.target.value='';}
};
$('lastPhoto').onclick=()=>{if($('lastPhoto').src)window.open($('lastPhoto').src,'_blank','noopener');};
