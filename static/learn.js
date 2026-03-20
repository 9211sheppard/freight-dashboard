// ─────────────────────────────────────────────────────────────────────────────
//  LEARNING SYSTEM  —  Quotes ticker + Learning sessions + Growth tracker
// ─────────────────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'wfa_growth';

// ── Growth tracker helpers ────────────────────────────────────────────────────
function loadProfile() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch { return {}; }
}

function saveProfile(p) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
}

function getProfile() {
  const p = loadProfile();
  if (!p.startDate) {
    p.startDate    = new Date().toISOString().slice(0, 10);
    p.totalScore   = 0;
    p.totalAnswered= 0;
    p.correct      = 0;
    p.streak       = 0;
    p.lastDate     = '';
    p.byBook       = {};
    p.history      = [];
    saveProfile(p);
  }
  return p;
}

function recordAnswer(bookId, correct) {
  const p   = getProfile();
  const today = new Date().toISOString().slice(0, 10);

  p.totalAnswered = (p.totalAnswered || 0) + 1;
  if (correct) {
    p.correct    = (p.correct || 0) + 1;
    p.totalScore = (p.totalScore || 0) + 10;
  }

  // Streak
  if (p.lastDate === today) {
    // already played today — streak unchanged
  } else if (p.lastDate === prevDay(today)) {
    p.streak = (p.streak || 0) + 1;
  } else {
    p.streak = 1;
  }
  p.lastDate = today;

  // Per-book
  if (!p.byBook[bookId]) p.byBook[bookId] = { answered: 0, correct: 0 };
  p.byBook[bookId].answered++;
  if (correct) p.byBook[bookId].correct++;

  // History (keep last 50)
  p.history = p.history || [];
  p.history.unshift({ date: today, bookId, correct, score: p.totalScore });
  if (p.history.length > 50) p.history.pop();

  saveProfile(p);
  return p;
}

function prevDay(dateStr) {
  const d = new Date(dateStr);
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function daysSince(dateStr) {
  if (!dateStr) return 0;
  const ms = Date.now() - new Date(dateStr).getTime();
  return Math.floor(ms / 86400000);
}

// ── Quote ticker ──────────────────────────────────────────────────────────────
let tickerIndex = 0;

function initTicker() {
  try {
    var el = document.getElementById('quoteTicker');
    if (!el) { console.warn('quoteTicker element not found'); return; }
    if (!ALL_QUOTES || !ALL_QUOTES.length) { console.warn('ALL_QUOTES empty'); return; }

    // Shuffle
    for (var i = ALL_QUOTES.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = ALL_QUOTES[i]; ALL_QUOTES[i] = ALL_QUOTES[j]; ALL_QUOTES[j] = tmp;
    }

    showQuote(el, 0);
    setInterval(function() {
      tickerIndex = (tickerIndex + 1) % ALL_QUOTES.length;
      showQuote(el, tickerIndex);
    }, 60000);
  } catch(e) { console.error('initTicker error:', e); }
}

function showQuote(el, idx) {
  try {
    var q = ALL_QUOTES[idx];
    el.innerHTML = '\u201c' + q.text + '\u201d <span class="ticker-attr">\u2014 ' + q.book + '</span>';
  } catch(e) { console.error('showQuote error:', e); }
}

// ── Modal HTML ────────────────────────────────────────────────────────────────
function buildModal() {
  const existing = document.getElementById('learnModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'learnModal';
  modal.className = 'learn-modal-overlay';
  modal.innerHTML = `
    <div class="learn-modal">
      <button class="learn-close" id="learnClose" title="Close">×</button>
      <div id="learnBody"></div>
    </div>`;
  document.body.appendChild(modal);

  document.getElementById('learnClose').addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });

  return document.getElementById('learnBody');
}

function closeModal() {
  const m = document.getElementById('learnModal');
  if (m) { m.classList.add('learn-modal-hide'); setTimeout(() => m.remove(), 250); }
}

// ── Screen: Book picker ───────────────────────────────────────────────────────
function showBookPicker() {
  const body = buildModal();
  const p    = getProfile();
  const days = daysSince(p.startDate);
  const pct  = p.totalAnswered ? Math.round((p.correct / p.totalAnswered) * 100) : 0;

  body.innerHTML = `
    <div class="learn-header">
      <div class="learn-title">📚 Learning Session</div>
      <div class="learn-subtitle">Pick a book to learn from</div>
    </div>

    <div class="growth-bar-row">
      <div class="growth-stat"><span class="gs-num">${p.totalScore || 0}</span><span class="gs-label">Points</span></div>
      <div class="growth-stat"><span class="gs-num">${pct}%</span><span class="gs-label">Accuracy</span></div>
      <div class="growth-stat"><span class="gs-num">${p.streak || 0}</span><span class="gs-label">🔥 Streak</span></div>
      <div class="growth-stat"><span class="gs-num">${days}</span><span class="gs-label">Days in</span></div>
    </div>

    <div class="book-grid">
      ${Object.values(BOOKS).map(book => {
        const bs   = (p.byBook || {})[book.id] || { answered: 0, correct: 0 };
        const bpct = bs.answered ? Math.round((bs.correct / bs.answered) * 100) : null;
        return `
          <button class="book-card" data-book="${book.id}" style="border-top:3px solid ${book.color}">
            <div class="book-icon">${book.icon}</div>
            <div class="book-card-title">${book.title}</div>
            <div class="book-card-author">${book.author}</div>
            ${bpct !== null ? `<div class="book-card-score" style="color:${book.color}">${bpct}% accuracy · ${bs.answered} answered</div>` : '<div class="book-card-score">Not started yet</div>'}
          </button>`;
      }).join('')}
    </div>

    <div class="learn-footer-note">Right answers = +10 points &nbsp;·&nbsp; Keep your streak alive daily</div>`;

  body.querySelectorAll('.book-card').forEach(btn => {
    btn.addEventListener('click', () => showLessonPicker(btn.dataset.book));
  });
}

// ── Screen: Lesson picker ─────────────────────────────────────────────────────
function showLessonPicker(bookId) {
  const book = BOOKS[bookId];
  const body = buildModal();

  body.innerHTML = `
    <div class="learn-header">
      <button class="learn-back" id="backToBooks">← Books</button>
      <div class="learn-title" style="color:${book.color}">${book.icon} ${book.title}</div>
      <div class="learn-subtitle">by ${book.author} — choose a lesson</div>
    </div>
    <div class="lesson-list">
      ${book.lessons.map((lesson, i) => `
        <button class="lesson-card" data-book="${bookId}" data-lesson="${i}">
          <div class="lesson-num" style="background:${book.color}">${i + 1}</div>
          <div>
            <div class="lesson-card-title">${lesson.title}</div>
            <div class="lesson-card-preview">${lesson.keyPoint}</div>
          </div>
          <i class="bi bi-chevron-right ms-auto"></i>
        </button>`).join('')}
    </div>`;

  document.getElementById('backToBooks').addEventListener('click', showBookPicker);
  body.querySelectorAll('.lesson-card').forEach(btn => {
    btn.addEventListener('click', () => showLesson(btn.dataset.book, parseInt(btn.dataset.lesson)));
  });
}

// ── Screen: Lesson ────────────────────────────────────────────────────────────
function showLesson(bookId, lessonIdx) {
  const book   = BOOKS[bookId];
  const lesson = book.lessons[lessonIdx];
  const body   = buildModal();

  body.innerHTML = `
    <div class="learn-header">
      <button class="learn-back" id="backToLessons">← Lessons</button>
      <div class="learn-title" style="color:${book.color}">${lesson.title}</div>
      <div class="learn-subtitle">${book.icon} ${book.title}</div>
    </div>
    <div class="lesson-body">${lesson.body}</div>
    <div class="key-point-box" style="border-left:4px solid ${book.color}">
      <strong>Key Point:</strong> ${lesson.keyPoint}
    </div>
    <button class="btn-quiz" id="startQuiz" style="background:${book.color}">
      <i class="bi bi-patch-question me-2"></i>Test Yourself
    </button>`;

  document.getElementById('backToLessons').addEventListener('click', () => showLessonPicker(bookId));
  document.getElementById('startQuiz').addEventListener('click', () => showQuiz(bookId, lessonIdx));
}

// ── Screen: Quiz ──────────────────────────────────────────────────────────────
function showQuiz(bookId, lessonIdx) {
  const book   = BOOKS[bookId];
  const lesson = book.lessons[lessonIdx];
  const quiz   = lesson.quiz;
  const body   = buildModal();

  body.innerHTML = `
    <div class="learn-header">
      <div class="learn-title" style="color:${book.color}">Quiz</div>
      <div class="learn-subtitle">${lesson.title}</div>
    </div>
    <div class="quiz-question">${quiz.q}</div>
    <div class="quiz-options" id="quizOptions">
      ${quiz.options.map((opt, i) => `
        <button class="quiz-opt" data-idx="${i}">${opt}</button>`).join('')}
    </div>
    <div class="quiz-result" id="quizResult" style="display:none"></div>
    <div class="quiz-actions" id="quizActions" style="display:none">
      <button class="btn-next" id="nextLesson">Next Lesson →</button>
      <button class="btn-back-book" id="backBook">Back to Books</button>
    </div>`;

  body.querySelectorAll('.quiz-opt').forEach(btn => {
    btn.addEventListener('click', () => {
      const chosen  = parseInt(btn.dataset.idx);
      const correct = chosen === quiz.answer;
      const p       = recordAnswer(bookId, correct);

      // Highlight answers
      body.querySelectorAll('.quiz-opt').forEach((b, i) => {
        b.disabled = true;
        if (i === quiz.answer) b.classList.add('quiz-correct');
        else if (i === chosen && !correct) b.classList.add('quiz-wrong');
      });

      // Result panel
      const res = document.getElementById('quizResult');
      res.style.display = 'block';
      res.innerHTML = correct
        ? `<div class="quiz-res-correct">✅ Correct! +10 points — Total: ${p.totalScore} | Streak: 🔥${p.streak}</div>
           <div class="quiz-explanation">${quiz.explanation}</div>`
        : `<div class="quiz-res-wrong">❌ Not quite — the answer is: <strong>${quiz.options[quiz.answer]}</strong></div>
           <div class="quiz-explanation">${quiz.explanation}</div>`;

      document.getElementById('quizActions').style.display = 'flex';

      // Next lesson button
      const nextIdx = lessonIdx + 1;
      const nextBtn = document.getElementById('nextLesson');
      if (nextIdx < book.lessons.length) {
        nextBtn.textContent = 'Next Lesson →';
        nextBtn.addEventListener('click', () => showLesson(bookId, nextIdx));
      } else {
        nextBtn.textContent = '🎉 Book Complete — All Lessons Done';
        nextBtn.addEventListener('click', showBookPicker);
      }
      document.getElementById('backBook').addEventListener('click', showBookPicker);
    });
  });
}

// ── Init — runs immediately since script is at bottom of body ─────────────────
(function init() {
  initTicker();
  const learnBtn = document.getElementById('learnBtn');
  if (learnBtn) learnBtn.addEventListener('click', showBookPicker);
})();
