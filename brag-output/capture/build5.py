# Builds the Brik-styled launch composition: cuts footage5 clips and writes composition/index.html.
import json, subprocess
M = '/root/.claude/plugins/synced/69b0f08a-ebfb-4acd-8eee-1a6cb7dcdca4_2ede87c9-cf0e-4607-ab20-d148c955ad35/brag/skills/brag/assets/music/cues/happy-beats-business-moves-vol-11-by-ende-dot-app.music-cues.json'
beats = [b['time'] for b in json.load(open(M))['beats']]
snap = lambda t: min(beats, key=lambda b: abs(b - t))
X = 0.4  # crossfade
# name, target dur, source start, speed, eyebrow, ink line, faded line
S = [
 ('overview', 4.0, 1.3, 1.0, 'Overview', 'Your business,', 'at a glance.'),
 ('explore', 4.0, 2.3, 1.0, 'Connections', 'Every record,', 'connected.'),
 ('details', 4.0, 5.6, 1.0, 'Record details', 'Open any record.', 'See all it touches.'),
 ('layouts', 4.0, 4.0, 1.3, 'Views', 'Your data,', 'your view.'),
 ('ask', 5.5, 2.6, 1.4, 'Ask', 'Just ask,', 'in plain English.'),
 ('trust', 3.5, 2.6, 1.3, 'Trust', 'Stays on your data.', 'Nothing else.'),
 ('map', 4.5, 4.0, 1.6, 'Action', 'Answer to records,', 'in one click.'),
 ('flows', 3.0, 2.7, 1.0, 'Flows', 'Follow the process,', 'order to cash.'),
 ('trace', 3.0, 2.0, 1.0, 'Trace', 'Trace any order', 'to payment.'),
]
t = snap(3.0); rows = []
for n, d, src, sp, e, a, b in S:
    start = round(t, 3); end = snap(start + d); dur = round(end - start, 3)
    clip = dur + X
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', str(src), '-t', str(round(clip * sp + 0.1, 2)), '-i', f'footage5/{n}.mp4',
                    '-vf', f'setpts=PTS/{sp},fps=30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-an', f'composition/assets/footage/{n}.mp4'], check=True)
    rows.append((n, start, dur, e, a, b)); t = end
OUT = round(t, 3); TOTAL = round(OUT + 3.6, 2)
N = len(rows)
vids, caps, js = [], [], []
for i, (n, s, d, e, a, b) in enumerate(rows):
    vids.append(f'  <video id="v_{n}" class="frame clip" data-track-index="{i+1}" src="assets/footage/{n}.mp4" data-start="{s}" data-duration="{round(d+X,3)}" data-media-start="0" muted playsinline></video>')
    caps.append(f'''  <div id="c_{n}" class="copy clip" data-start="{s}" data-duration="{d}" data-track-index="{20+i}">
    <div class="eyebrow">[ {i+1:02d} ] {e.upper()}</div>
    <div class="head"><span class="l1">{a}</span><span class="l2">{b}</span></div>
  </div>''')
    js.append(f'scene("#v_{n}","#c_{n}",{s},{d},{i+1}); // beat-locked: {s}s')
html = open('capture/template5.html').read()
html = (html.replace('%VIDS%', '\n'.join(vids)).replace('%CAPS%', '\n'.join(caps)).replace('%JS%', '\n'.join(js))
        .replace('%TOTAL%', str(TOTAL)).replace('%OUT%', str(OUT)).replace('%N%', str(N)).replace('%FIRST%', str(rows[0][1])))
open('composition/index.html', 'w').write(html)
print('total', TOTAL, [(r[0], r[1], r[2]) for r in rows])
