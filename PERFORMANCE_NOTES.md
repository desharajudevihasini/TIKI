# Where latency comes from

**Ordinary voice:** browser microphone → Chrome SpeechRecognition (if available) OR single Gemini call for both transcript + reply → local Mac speech synthesis → ESP32 audio POST and speaker playback.

**Camera:** physical button → ESP32 JPEG via Wi-Fi → Gemini Vision → local photo+description → Mac TTS → ESP32 speaker.

The fast audio path avoids one of two sequential Gemini requests (old STT then AI). The app falls back to the proven two-request path if the new JSON response is unsupported. Browser speech recognition may still be faster in Chrome, but accuracy depends on browser/service. The model list is cached within the process. Wake speech also uses the single-call path. Shorter TTS reduces speaker delivery time. None of these changes guarantees a fixed speed during cloud overload.

**If still slow:** compare response time for typed messages and voice. Typed slow = Gemini or speaker; typed fast but voice slow = speech recognition or upload. If the ESP32 cannot answer `curl http://ACTUAL_IP/button`, fix Wi-Fi first; otherwise speakers cannot receive any answer.
