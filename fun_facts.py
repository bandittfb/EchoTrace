"""Rotating content for the waiting screen."""
import random

INVESTIGATION_FACTS = [
    "The first polygraph was invented in 1921 by a UC Berkeley medical student.",
    "The FBI's first wiretap was authorized in 1928 during the Prohibition era.",
    "Fingerprinting was first used to solve a murder in Argentina in 1892.",
    "The average person speaks about 125 words per minute but can listen at 400 WPM.",
    "Body cameras were first widely adopted by U.S. police departments in 2014.",
    "Forensic voice analysis can identify speakers with over 95% accuracy in ideal conditions.",
    "The first CCTV system was installed in 1942 to monitor V-2 rocket launches in Germany.",
    "Audio forensics experts can detect edits as small as 1/100th of a second.",
    "The word 'detective' first appeared in English around 1843.",
    "Sherlock Holmes first appeared in print in 1887 in 'A Study in Scarlet.'",
    "The average interrogation in the U.S. lasts about 1.6 hours.",
    "Human ears can distinguish over 400,000 different sounds.",
    "The first 911 call in the United States was made on February 16, 1968.",
    "Digital audio evidence was first admitted in a U.S. court in 1981.",
    "The Miranda warning became law after the 1966 Supreme Court ruling in Miranda v. Arizona.",
    "A whisper is typically about 30 decibels — roughly the volume of rustling leaves.",
    "The CIA developed a voice-changing device in the 1960s codenamed 'Acoustic Kitty.'",
    "The first private detective agency was founded by Eugène François Vidocq in 1833.",
    "Over 80% of criminal cases in the U.S. involve some form of digital evidence.",
    "Sound travels about 4.3 times faster through water than through air.",
]

ECHOTRACE_TIPS = [
    "Tip: Press F5 to play/pause audio without leaving the text editor.",
    "Tip: Press F6 to rewind 5 seconds — perfect for catching missed words.",
    "Tip: Press F7 to skip forward 5 seconds.",
    "Tip: Click any timestamp in the editor to jump directly to that moment.",
    "Tip: Use the speed buttons to slow audio down to 0.5x for difficult sections.",
    "Tip: Export to DOCX for court-ready formatting with timestamps.",
    "Tip: Export to PDF for easy sharing with attorneys or clients.",
    "Tip: Save your project as .echotrace to come back and finish editing later.",
    "Tip: Speaker Detection labels each voice as Speaker 1, Speaker 2, etc.",
    "Tip: Use the 'small' or 'medium' model for better accuracy on tough audio.",
    "Tip: The 'large-v3' model is the most accurate but takes longer to process.",
    "Tip: You can edit speaker names directly in the transcript text.",
    "Tip: The JSON export includes structured data — great for case management systems.",
    "Tip: Drag and drop audio files directly onto the app window.",
    "Tip: Your HuggingFace token is stored locally in .env — never uploaded anywhere.",
]

INVESTIGATOR_QUOTES = [
    '"When you have eliminated the impossible, whatever remains, however improbable, must be the truth."\n— Sherlock Holmes',
    '"The world is full of obvious things which nobody ever observes."\n— Sherlock Holmes',
    '"There is nothing more deceptive than an obvious fact."\n— Sherlock Holmes',
    '"It is a capital mistake to theorize before one has data."\n— Sherlock Holmes',
    '"A good detective never gets married."\n— Raymond Chandler',
    '"The truth is rarely pure and never simple."\n— Oscar Wilde',
    '"Facts do not cease to exist because they are ignored."\n— Aldous Huxley',
    '"In the middle of difficulty lies opportunity."\n— Albert Einstein',
    '"The devil is in the details."\n— Common investigator wisdom',
    '"Trust, but verify."\n— Ronald Reagan',
    '"Evidence does not lie. People do."\n— Anonymous forensic examiner',
    '"Every contact leaves a trace."\n— Edmond Locard (Locard\'s Exchange Principle)',
    '"Observation is a dying art."\n— Stanley Kubrick',
    '"The best way to find out if you can trust somebody is to trust them."\n— Ernest Hemingway',
    '"Listen to the evidence, not the noise."\n— Anonymous investigator',
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
