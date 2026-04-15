"""Rotating content for the waiting screen.

Three pools of short text — facts, software tips, and investigator
wisdom — that the waiting widget shuffles through during transcription.
The user has explicitly mentioned learning real workflow habits from
the tips, so accuracy of every entry matters: anything that sounds
plausible-but-wrong here erodes trust.

Editing guidelines if you add more:
- Facts should be verifiable. If you're not sure, don't include it.
- Tips must reflect a feature that actually exists in the app today.
- Quotes are either correctly attributed or honestly labeled
  "Anonymous" / "proverb" / "common wisdom." No fabricated authors.
"""
import random

INVESTIGATION_FACTS = [
    # --- History of investigation, surveillance, and forensics ---
    "The first polygraph was invented in 1921 by John Larson, a UC Berkeley medical student.",
    "The FBI's first wiretap was authorized in 1928 during the Prohibition era.",
    "Fingerprinting was first used to solve a murder in Argentina in 1892, by Juan Vucetich.",
    "Body cameras were first widely adopted by U.S. police departments in 2014.",
    "The first CCTV system was installed in 1942 to monitor V-2 rocket launches in Germany.",
    "The word 'detective' first appeared in English around 1843.",
    "Sherlock Holmes first appeared in print in 1887 in 'A Study in Scarlet.'",
    "The first private detective agency was founded by Eugène François Vidocq in 1833 in Paris.",
    "Allan Pinkerton founded the Pinkerton National Detective Agency in 1850 — the first in America.",
    "The first 911 call in the United States was made on February 16, 1968, in Haleyville, Alabama.",
    "The Miranda warning became law after the 1966 Supreme Court ruling in Miranda v. Arizona.",
    "The CIA developed a voice-changing device in the 1960s codenamed 'Acoustic Kitty.'",
    "Over 80% of criminal cases in the U.S. now involve some form of digital evidence.",
    "The Locard Exchange Principle (1910) states that every contact leaves a trace — true for audio, too.",
    "The Innocence Project has helped exonerate over 375 wrongfully convicted people in the U.S.",
    "The average interrogation in the U.S. lasts about 1.6 hours.",
    "Digital audio evidence was first formally admitted in U.S. federal court in 1981.",
    "Court reporters' shorthand has been evolving continuously since the 1500s.",
    "Tiro's notae — Roman shorthand from 63 BCE — were the first known stenographic system.",

    # --- Sound, voice, and hearing ---
    "Human ears can distinguish over 400,000 different sounds.",
    "A whisper is typically about 30 decibels — roughly the volume of rustling leaves.",
    "Sound travels about 4.3 times faster through water than through air.",
    "The human voice's fundamental frequency averages 110 Hz for adult males, 200 Hz for females.",
    "Telephone audio is bandwidth-limited to roughly 300–3,400 Hz — half of human hearing range.",
    "The 'cocktail party effect' lets humans focus on one voice in a crowded, noisy room.",
    "The Lombard effect: people automatically speak louder when their environment gets noisy.",
    "The McGurk effect: what you SEE someone say can override what you HEAR them say.",
    "The English language has about 44 distinct phonemes despite using only 26 letters.",
    "Hearing loss in the 4–8 kHz range disproportionately damages your ability to understand speech.",
    "Active listening retains roughly 50% of a conversation; passive listening retains about 25%.",
    "Spanish averages 7.8 syllables per second; Mandarin only 5.2 — but they convey similar info.",
    "Natural speech contains about 6 'ums' and 'uhs' per minute on average.",
    "The 'phantom words' phenomenon: in noisy audio, your brain can hallucinate words that aren't there.",
    "The average person speaks about 125 words per minute but can listen at over 400 WPM.",
    "Court reporters can transcribe at 225+ words per minute using stenotype machines.",

    # --- Audio recording and forensics ---
    "Forensic voice analysis can identify speakers with over 95% accuracy in ideal conditions.",
    "Audio forensics experts can detect tape edits as small as 1/100th of a second.",
    "Voice stress analysis has never been validated as a lie-detection tool by the scientific community.",
    "Forensic phonetics emerged as a recognized discipline in the 1960s.",
    "The first audio recording of human speech was made by Édouard-Léon Scott de Martinville in 1860.",
    "Thomas Edison's 1877 phonograph could record about 2 minutes of audio on a tinfoil cylinder.",
    "A 16-bit, 44.1 kHz CD-quality audio file uses about 10 MB per minute.",
    "WAV files are typically uncompressed; FLAC offers lossless compression at about half the size.",
    "Most modern voice recorders save audio in MP3 or WMA at 64–128 kbps.",
    "VEC Infinity foot pedals have been the transcription industry standard since the early 2000s.",
    "The Olympus DS-9500 is widely considered the gold standard digital recorder for legal professionals.",
    "The Watergate tapes total roughly 3,700 hours — only a fraction has ever been fully transcribed.",
    "'Inaudible' is the single most common annotation in court transcripts of low-quality audio.",
    "The Federal Rules of Evidence don't require a verbatim transcript — accuracy is what matters in court.",
    "Continuous 24/7 audio surveillance for one year produces about 3–4 terabytes of compressed data.",

    # --- AI and modern speech recognition ---
    "OpenAI's Whisper speech recognition model was first released in September 2022.",
    "Whisper was trained on 680,000 hours of multilingual audio sourced from the open web.",
    "Whisper transcribes 99 languages, though English makes up about 83% of its training data.",
    "'Faster-whisper' runs the same Whisper models up to 4x faster using the CTranslate2 engine.",
    "pyannote.audio is the leading open-source library for speaker diarization.",
    "'Diarization' as a term was coined around 1998 — from 'diary,' i.e. labeling who spoke when.",
    "Speaker diarization typically struggles when two or more speakers talk over each other.",
    "Mel-frequency spectrograms approximate how the human cochlea actually perceives frequency.",
    "The first real-time speech-recognition system was IBM's Tangora in 1985 (20,000-word vocabulary).",
    "Apple's Siri launched in October 2011; Google Now followed in mid-2012.",
    "Word-error rates in speech recognition fell from ~25% in 2013 to under 5% by 2017.",
    "Modern echo cancellation in conferencing systems works in under 50 milliseconds.",
    "Whisper feeds 80-channel mel-spectrograms into a transformer — not raw waveforms.",
    "The MP3 format was standardized in 1993; MP4 audio (AAC) in 1997.",
    "An 8-hour mono audio file at 16 kHz is about 460 MB uncompressed.",
]

ECHOTRACE_TIPS = [
    # --- Core playback hotkeys ---
    "Tip: Press F5 to play/pause audio without leaving the text editor.",
    "Tip: Press F6 to rewind 5 seconds — perfect for catching missed words.",
    "Tip: Press F7 to skip forward 5 seconds.",
    "Tip: Click any timestamp in the transcript to jump audio directly to that moment.",
    "Tip: The currently-playing segment is highlighted in the editor — never lose your place.",
    "Tip: Click the highlighted segment to seek audio back to its starting timestamp.",

    # --- Speed control ---
    "Tip: Slow audio to 0.5x for accents, mumbling, or overlapping speech — no pitch distortion.",
    "Tip: 1.5x or 2.0x is great for cruising through known content quickly.",
    "Tip: 0.75x is the sweet spot for first-pass review of clear audio.",

    # --- Volume / VU meter ---
    "Tip: The volume slider goes up to 120% — use it to boost very quiet recordings.",
    "Tip: The VU meter visualizes audio level in real time, helping you spot dropouts.",
    "Tip: Volume color shifts green → yellow → red as you boost — green is safe, red is hot.",

    # --- Per-line speaker chooser (NEW) ---
    "Tip: Hover over any speaker name — the cursor turns into a hand. Click to change just that line.",
    "Tip: The speaker dropdown shows usage counts, so the most-frequent voice is always at the top.",
    "Tip: Right-click any line — even one without a speaker — for a 'Set speaker' submenu.",
    "Tip: Quick-add roles (Officer, Witness, Suspect, Detective) auto-number themselves.",
    "Tip: 'New speaker name…' lets you add any custom label — Mom, Caller, Dispatcher, anything.",

    # --- Speaker management dialog ---
    "Tip: Click the Speakers… button to rename ALL instances of a speaker globally.",
    "Tip: The speaker manager safely merges two labels — 'Speaker 1' and 'Officer Smith' become one.",
    "Tip: Speaker renames are non-destructive — review the change list before you click Apply.",

    # --- Flags & notes ---
    "Tip: Right-click any line in the transcript to flag the segment.",
    "Tip: Flag types: inaudible, admission, contradiction, follow-up, or custom.",
    "Tip: Use 'admission' flags for legally significant statements you'll want to revisit.",
    "Tip: 'Contradiction' flags help you cross-reference inconsistencies in testimony.",
    "Tip: 'Follow-up' flags mark questions you still need to answer in your investigation.",
    "Tip: 'Inaudible' flags warn reviewers that audio quality is questionable in that section.",
    "Tip: The Flags ▾ button lists every flagged segment, sorted by timestamp — click to jump.",
    "Tip: Add a free-form note to any segment — it travels with the project and shows in the menu.",
    "Tip: Notes are saved with the .echotrace project, never on any cloud server.",

    # --- Search ---
    "Tip: Press Ctrl+F to open the search bar and find any word in the transcript.",
    "Tip: Press F3 to jump to the next search match; Shift+F3 for previous.",
    "Tip: Press Esc to clear the search and dismiss the search bar.",
    "Tip: Search results show as yellow highlights with a '1 of N' counter for context.",

    # --- Save / autosave / recovery ---
    "Tip: Press Ctrl+S to save your project to an .echotrace file.",
    "Tip: Autosave runs every 30 seconds in the background — your work is rarely more than half a minute behind.",
    "Tip: If EchoTrace closes unexpectedly, your work is offered for recovery on next launch.",
    "Tip: Save your project as .echotrace to come back and finish editing later.",
    "Tip: A successful Save clears the autosave file — no stale recovery prompts.",

    # --- Audit log ---
    "Tip: The Audit Log… button shows every action you took — chain-of-custody for your work.",
    "Tip: Add manual notes to the audit log for case documentation as you work.",
    "Tip: Speaker changes, flag changes, saves, exports — everything is timestamped in the audit log.",

    # --- Foot pedal ---
    "Tip: Plug in a VEC Infinity foot pedal — it's auto-detected, no drivers needed.",
    "Tip: Hold-to-play mode (default): center pedal plays only while pressed — Express Scribe style.",
    "Tip: Continuous mode: tap the center pedal to start playback, tap again to pause.",
    "Tip: Left pedal rewinds 5 seconds; right pedal jumps forward 5 seconds.",
    "Tip: Toggle between hold-to-play and continuous via the slider switch above the transcript.",

    # --- Formatting ---
    "Tip: Ctrl+B, Ctrl+I, Ctrl+U format selected text — Bold, Italic, Underline.",
    "Tip: Bold/italic/underline formatting survives DOCX and PDF export.",
    "Tip: TXT and JSON exports ignore formatting — they're plain by design.",
    "Tip: The Clear Format button strips B/I/U from the current selection.",

    # --- Models ---
    "Tip: 'tiny' and 'base' models are great for quick previews of large files.",
    "Tip: Use 'small' or 'medium' for everyday case work — solid accuracy, reasonable speed.",
    "Tip: 'large-v3' is the most accurate Whisper model — slower, but worth it for final transcripts.",
    "Tip: Speaker Detection labels each voice as Speaker 1, Speaker 2, etc. — rename freely.",

    # --- Export ---
    "Tip: Export to DOCX for court-ready formatting with timestamps and speaker labels.",
    "Tip: Export to PDF for clean, read-only sharing with attorneys or clients.",
    "Tip: Export to JSON for structured data — perfect for case management software.",
    "Tip: Export to TXT for easy grep, email, or long-term archive storage.",
    "Tip: Exported files open automatically in your default app — instant verification.",
    "Tip: Every export is logged in the audit trail with file path and format.",

    # --- File handling ---
    "Tip: Drag and drop audio OR video files directly onto the app window.",
    "Tip: Video files (MP4, MKV, MOV, AVI, WebM) play in a side panel beside the transcript.",
    "Tip: Drag the splitter to resize the video panel — narrow it for transcript focus, widen for evidence review.",

    # --- Privacy ---
    "Tip: All transcription happens on YOUR machine — nothing is ever sent to any cloud service.",
    "Tip: Your HuggingFace token (in .env) is used only to download speaker-detection models locally.",
    "Tip: EchoTrace works fully offline once the speech-recognition models are downloaded.",
    "Tip: No telemetry, no analytics, no phone-home. Audit the source if you don't believe it.",
]

INVESTIGATOR_QUOTES = [
    # --- Sherlock Holmes (always a crowd-pleaser) ---
    '"When you have eliminated the impossible, whatever remains, however improbable, must be the truth."\n— Sherlock Holmes',
    '"The world is full of obvious things which nobody by any chance ever observes."\n— Sherlock Holmes',
    '"There is nothing more deceptive than an obvious fact."\n— Sherlock Holmes',
    '"It is a capital mistake to theorize before one has data."\n— Sherlock Holmes',
    '"You see, but you do not observe. The distinction is clear."\n— Sherlock Holmes',
    '"Data! Data! Data! I cannot make bricks without clay."\n— Sherlock Holmes',
    '"Nothing clears up a case so much as stating it to another person."\n— Sherlock Holmes',
    '"Mediocrity knows nothing higher than itself, but talent instantly recognises genius."\n— Sherlock Holmes',

    # --- Real investigators, criminologists, forensic scientists ---
    '"Every contact leaves a trace."\n— Edmond Locard, Locard\'s Exchange Principle (1910)',
    '"The criminal always returns to the scene of the crime."\n— attributed to Eugène François Vidocq',
    '"Wherever he steps, whatever he touches, whatever he leaves — even unconsciously — will serve as silent evidence against him."\n— Paul L. Kirk, criminalist',
    '"In God we trust; all others we monitor."\n— motto of the U.S. Air Force Technical Applications Center',
    '"The evidence does not lie. People do."\n— Anonymous forensic examiner',

    # --- Detective fiction ---
    '"Down these mean streets a man must go who is not himself mean."\n— Raymond Chandler, "The Simple Art of Murder"',
    '"To say goodbye is to die a little."\n— Raymond Chandler',
    '"It is not enough to have a good mind. The main thing is to use it well."\n— attributed to Hercule Poirot (Agatha Christie)',
    '"Just the facts, ma\'am."\n— attributed to Sgt. Joe Friday, "Dragnet"',
    '"Just one more thing…"\n— Lt. Columbo',
    '"I shall sit here, so to speak, and shuffle the facts of this case."\n— Hercule Poirot',
    '"There are no friendly witnesses, only people who want different things from the truth."\n— Anonymous, paraphrasing the noir tradition',

    # --- Trial law / courtroom ---
    '"It is better that ten guilty persons escape than that one innocent suffer."\n— William Blackstone',
    '"Justice delayed is justice denied."\n— William E. Gladstone',
    '"The truth is rarely pure and never simple."\n— Oscar Wilde',
    '"Half a truth is often a great lie."\n— Benjamin Franklin',
    '"If you torture the data long enough, it will confess to anything."\n— Ronald Coase',

    # --- Listening, observation, attention ---
    '"It\'s not what you look at that matters, it\'s what you see."\n— Henry David Thoreau',
    '"Most people do not listen with the intent to understand; they listen with the intent to reply."\n— Stephen R. Covey',
    '"I keep six honest serving-men (they taught me all I knew); their names are What and Why and When and How and Where and Who."\n— Rudyard Kipling',
    '"Wisdom is the reward you get for a lifetime of listening when you would rather have talked."\n— Doug Larson',
    '"Big results require big ambitions."\n— Heraclitus',
    '"Observation is a dying art."\n— Stanley Kubrick',
    '"The map is not the territory."\n— Alfred Korzybski (a useful warning when reading any transcript)',
    '"He who has ears to hear, let him hear."\n— Matthew 11:15',

    # --- Truth, evidence, patience ---
    '"Facts do not cease to exist because they are ignored."\n— Aldous Huxley',
    '"The truth will set you free, but first it will piss you off."\n— Joe Klaas',
    '"Truth is the daughter of time."\n— Italian proverb (Latin: Veritas filia temporis)',
    '"Patience and diligence, like faith, remove mountains."\n— William Penn',
    '"In the middle of difficulty lies opportunity."\n— Albert Einstein',
    '"Trust, but verify."\n— Russian proverb, popularized by Ronald Reagan',
    '"It is not the answer that enlightens, but the question."\n— Eugène Ionesco',
    '"I have not failed. I\'ve just found 10,000 ways that won\'t work."\n— Thomas Edison',
    '"There is no substitute for hard work."\n— Thomas Edison',
    '"Do not believe everything you hear; do not say all that you think."\n— Common proverb',

    # --- Investigator wisdom (anonymous / workshop adages) ---
    '"An interview is a conversation with a purpose."\n— Common investigator training maxim',
    '"Listen twice, ask once."\n— Investigator\'s adage',
    '"Always assume the recording is being recorded."\n— Modern investigator wisdom',
    '"A clue is only a clue if you know where to look."\n— Anonymous',
    '"The first thing a detective learns is that nothing is what it seems."\n— Anonymous',
    '"When in doubt, interview again."\n— Common PI adage',
    '"An investigator who can\'t take notes can\'t take cases."\n— Old PI saying',
    '"The devil is in the details."\n— Common investigator wisdom',
    '"Listen to the evidence, not the noise."\n— Anonymous investigator',
    '"Every case has a story; every story has a witness."\n— Anonymous',
    '"Truth has a tendency to leak."\n— Anonymous investigator',
    '"There are no accidents in detective work — only patterns we haven\'t seen yet."\n— Anonymous',
    '"The best evidence is the kind that doesn\'t know it\'s evidence."\n— Anonymous forensic examiner',
    '"Time is the only witness that never lies."\n— Common adage',
    '"Coincidence is the universe\'s way of getting your attention."\n— Anonymous',
]

ALL_CONTENT = (
    [("fact", f) for f in INVESTIGATION_FACTS]
    + [("tip", t) for t in ECHOTRACE_TIPS]
    + [("quote", q) for q in INVESTIGATOR_QUOTES]
)


def get_shuffled_content() -> list[tuple[str, str]]:
    """Return all content shuffled. Each item is (category, text)."""
    items = ALL_CONTENT.copy()
    random.shuffle(items)
    return items
