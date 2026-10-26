# Builds the Brik-styled launch composition: cuts footage5 clips and writes composition/index.html.
import json, subprocess, sys
# argv: beats json (hyperframes beats output or a cue preset), music file name in composition/assets/music
raw = json.load(open(sys.argv[1])); MUSIC = sys.argv[2]
raw = raw.get('beats', raw) if isinstance(raw, dict) else raw
beats = [b['time'] if isinstance(b, dict) else float(b) for b in raw]
snap = lambda t: min(beats, key=lambda b: abs(b - t))
X = 0.4  # crossfade
# name, target dur, source start, speed, eyebrow, ink line, faded line
S = [
 ('overview', 3.0, 1.3, 1.0, 'Overview', 'Your business,', 'at a glance.'),
 ('explore', 3.0, 2.3, 1.0, 'Connections', 'Every record,', 'connected.'),
 ('details', 3.4, 5.6, 1.0, 'Record details', 'Open any record.', 'See all it touches.'),
 ('layouts', 3.4, 4.0, 1.6, 'Views', 'Your data,', 'your view.'),
 ('ask', 4.4, 2.6, 1.6, 'Ask', 'Just ask,', 'in plain English.'),
 ('trust', 3.0, 2.6, 1.5, 'Trust', 'Stays on your data.', 'Nothing else.'),
 ('map', 3.8, 4.0, 1.9, 'Action', 'Answer to records,', 'in one click.'),
 ('flows', 2.6, 2.7, 1.0, 'Flows', 'Follow the process,', 'order to cash.'),
 ('trace', 2.6, 2.0, 1.0, 'Trace', 'Trace any order', 'to payment.'),
]
t = snap(2.2); rows = []
for n, d, src, sp, e, a, b in S:
    start = round(t, 3); end = snap(start + d); dur = round(end - start, 3)
    clip = dur + X
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', str(src), '-t', str(round(clip * sp + 0.1, 2)), '-i', f'footage5/{n}.mp4',
                    '-vf', f'setpts=PTS/{sp},fps=30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-an', f'composition/assets/footage/{n}.mp4'], check=True)
    rows.append((n, start, dur, e, a, b)); t = end
OUT = round(t, 3); TOTAL = round(OUT + 3.0, 2)
N = len(rows)
vids, caps, js = [], [], []
for i, (n, s, d, e, a, b) in enumerate(rows):
    vids.append(f'  <video id="v_{n}" class="frame clip" data-track-index="{i+1}" src="assets/footage/{n}.mp4" data-start="{s}" data-duration="{round(d+X,3)}" data-media-start="0" muted playsinline></video>')
    caps.append(f'''  <div id="c_{n}" class="copy clip" data-start="{s}" data-duration="{d}" data-track-index="{20+i}">
    <div class="eyebrow">[ {i+1:02d} ] {e.upper()}</div>
    <div class="head"><span class="l1">{a}</span><span class="l2">{b}</span></div>
  </div>''')
    js.append(f'scene("#v_{n}","#c_{n}",{s},{d},{i+1}); // beat-locked: {s}s')
html = open('capture/template6.html').read()
html = (html.replace('%VIDS%', '\n'.join(vids)).replace('%CAPS%', '\n'.join(caps)).replace('%JS%', '\n'.join(js))
        .replace('%TOTAL%', str(TOTAL)).replace('%OUT%', str(OUT)).replace('%N%', str(N)).replace('%FIRST%', str(rows[0][1])).replace('%MUSIC%', MUSIC))
open('composition/index.html', 'w').write(html)
print('total', TOTAL, [(r[0], r[1], r[2]) for r in rows])
