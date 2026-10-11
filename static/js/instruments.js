// Orchestra instrument catalog.
// id must exactly match ORCHESTRA_INSTRUMENTS in the backend (app.py).
// sf  : instrument folder name in gleitz midi-js-soundfonts (FluidR3_GM), used for previews
// note: representative note played for the preview
// desc: one-line description for beginners

const SF_BASE = "https://gleitz.github.io/midi-js-soundfonts/FluidR3_GM";

export const INSTRUMENT_GROUPS = [
  {
    group: "Strings",
    items: [
      { id: "violin", name: "Violin", sf: "violin", note: "A4", desc: "The highest-pitched string instrument. Usually carries the melody." },
      { id: "viola", name: "Viola", sf: "viola", note: "C4", desc: "A bit lower and warmer than the violin, in the middle range." },
      { id: "cello", name: "Cello", sf: "cello", note: "C3", desc: "Warm, deep low-to-mid range. Sings like a voice." },
      { id: "contrabass", name: "Contrabass", sf: "contrabass", note: "A2", desc: "The lowest string instrument in the orchestra. Lays the foundation." },
      { id: "harp", name: "Harp", sf: "orchestral_harp", note: "C4", desc: "Plucked strings that produce sparkling arpeggios." },
    ],
  },
  {
    group: "Woodwinds",
    items: [
      { id: "flute", name: "Flute", sf: "flute", note: "C5", desc: "Clear, bright high notes. Bird-like tone." },
      { id: "piccolo", name: "Piccolo", sf: "piccolo", note: "C6", desc: "An octave above the flute. Very sharp and piercing." },
      { id: "oboe", name: "Oboe", sf: "oboe", note: "D5", desc: "A distinctive, nasal tone. Great for plaintive melodies." },
      { id: "clarinet", name: "Clarinet", sf: "clarinet", note: "D4", desc: "Smooth, round tone with a wide range." },
      { id: "bassoon", name: "Bassoon", sf: "bassoon", note: "C3", desc: "The low voice of the woodwinds — comical or solemn." },
    ],
  },
  {
    group: "Brass",
    items: [
      { id: "trumpet", name: "Trumpet", sf: "trumpet", note: "C5", desc: "Bright, piercing high notes. Used for fanfares and marches." },
      { id: "french_horn", name: "French Horn", sf: "french_horn", note: "C4", desc: "Round, majestic tone. Heroic mood." },
      { id: "trombone", name: "Trombone", sf: "trombone", note: "C3", desc: "A thick low brass instrument that changes pitch with a slide." },
      { id: "tuba", name: "Tuba", sf: "tuba", note: "C2", desc: "The lowest brass sound. A heavy, weighty foundation." },
    ],
  },
  {
    group: "Percussion & Keys",
    items: [
      { id: "timpani", name: "Timpani", sf: "timpani", note: "C3", desc: "Large pitched drums. Thunderous rumble and emphasis." },
      { id: "piano", name: "Piano", sf: "acoustic_grand_piano", note: "C4", desc: "Wide range. Can play harmony and melody at once." },
    ],
  },
];

export const ALL_INSTRUMENTS = INSTRUMENT_GROUPS.flatMap((g) => g.items);

export function instrumentById(id) {
  return ALL_INSTRUMENTS.find((i) => i.id === id) || null;
}

// Creates a preview audio element. Falls back to common notes if the target note is missing.
export function makePreviewAudio(inst) {
  const candidates = [inst.note, "C4", "C3", "A3"].filter(Boolean);
  const audio = new Audio();
  audio.preload = "none";
  let i = 0;
  const setSrc = () => {
    audio.src = `${SF_BASE}/${inst.sf}-mp3/${candidates[i]}.mp3`;
  };
  setSrc();
  audio.addEventListener("error", () => {
    if (i < candidates.length - 1) {
      i += 1;
      setSrc();
      audio.play().catch(() => {});
    }
  });
  return audio;
}
