import { getSelectedLanguage, setSelectedLanguage } from './appState.js';

export function initLanguageSelector() {
    // Quick language buttons were removed from the UI; this remains a
    // harmless no-op if none are present.
    const buttons = document.querySelectorAll('.lang-btn');
    const currentLang = getSelectedLanguage();

    buttons.forEach(btn => {
        const isActive = btn.dataset.lang === currentLang;
        btn.classList.toggle('active', isActive);

        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            setSelectedLanguage(btn.dataset.lang);
        });
    });
}

export { getSelectedLanguage } from './appState.js';

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let timerInterval = null;
let recordStartTime = 0;

function formatDuration(ms) {
    const totalSec = Math.floor(ms / 1000);
    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    return `${min}:${String(sec).padStart(2, '0')}`;
}

function startTimer(micBtn) {
    recordStartTime = Date.now();
    micBtn.textContent = '⏹ 0:00';
    timerInterval = setInterval(() => {
        micBtn.textContent = `⏹ ${formatDuration(Date.now() - recordStartTime)}`;
    }, 250);
}

function stopTimer(micBtn) {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
    micBtn.textContent = '🎙️';
}

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
                    stream.getTracks().forEach(track => track.stop());
                });

                mediaRecorder.start();
                isRecording = true;
                micBtn.classList.add('recording');
                startTimer(micBtn);
            } catch (err) {
                console.error('Mic access denied or unavailable:', err);
                alert("Couldn't access your microphone. Check browser permissions.");
            }
        } else {
            mediaRecorder.stop();
            isRecording = false;
            micBtn.classList.remove('recording');
            stopTimer(micBtn);
        }
    });
}