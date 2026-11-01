# TIKI — 60-second TreeHacks demo

**Pitch:** "TIKI is a DIY wearable visual-memory companion: it captures a scene with a consent-based hardware camera button, helps interpret what it sees, remembers it, and speaks through its own speaker."

1. **Show the wearable (10s).** Point out ESP32-S3, camera, physical camera button, privacy LED, MAX98357A speaker. Explain that Mac microphone + Gemini are the MVP compute/voice gateway; there is no onboard mic yet.
2. **Speak (15s).** Click **Talk** in the minimal TIKI app. Say, "Hey TIKI, spots on. What can you do?" Click **Finish speaking**. The app transcribes; TIKI replies through the actual speaker.
3. **Take a real picture (20s).** Use Talk: "TIKI, look at this and tell me what you see." Finish, aim the camera, and **tap the physical button once**. The camera saves one real photo; TIKI describes it aloud.
4. **Remember (15s).** Ask on-screen, "What did you see in that photo earlier?" Show the **Photos** library with image, timestamp and saved description.

If a question or photo analysis takes 10–20 seconds due to Gemini demand, don't claim real-time sub-second inference. Show actual feedback in the app rather than cutting the video to imply instant response.

**Buttons are never interchangeable:** hardware = camera; on-screen = microphone. The LED on the older firmware might toggle rather than correctly indicate active capture, so don't make an unverified privacy indicator claim.
