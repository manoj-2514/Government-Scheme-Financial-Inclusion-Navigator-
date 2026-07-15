let selectedLanguage = ''; // '' means auto-detect

export function initLanguageSelector() {
    const buttons = document.querySelectorAll('.lang-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedLanguage = btn.dataset.lang;
        });
    });
}

export function getSelectedLanguage() {
    return selectedLanguage;
}

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

export function initMicButton(onRecordingComplete) {
    const micBtn = document.getElementById('mic-btn');

    micBtn.addEventListener('click', async () => {
        if (!isRecording) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];

                mediaRecorder.addEventListener('dataavailable', (e) => {
                    audioChunks.push(e.data);
                });

                mediaRecorder.addEventListener('stop', () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    onRecordingComplete(audioBlob);
                    stream.getTracks().forEach(track => track.stop()); // releases the mic
                });

                mediaRecorder.start();
                isRecording = true;
                micBtn.classList.add('recording');
                micBtn.textContent = '⏹️';
            } catch (err) {
                console.error('Mic access denied or unavailable:', err);
                alert("Couldn't access your microphone. Check browser permissions.");
            }
        } else {
            mediaRecorder.stop();
            isRecording = false;
            micBtn.classList.remove('recording');
            micBtn.textContent = '🎙️';
        }
    });
}