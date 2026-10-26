# Synthesised hard-rock bed: 150 BPM, 30s, distorted power chords, bass, kick/snare/hats, crash accents.
import numpy as np, wave
SR=44100; BPM=150; beat=60/BPM; DUR=30.0
N=int(SR*DUR); t=np.arange(N)/SR
rng=np.random.default_rng(7)
mix=np.zeros(N)
def add(buf,start,sig,g=1.0):
    i=int(start*SR); j=min(N,i+len(sig))
    if i<N: buf[i:j]+=sig[:j-i]*g
def env(n,a=0.003,d=0.2):
    x=np.arange(n)/SR; return np.minimum(1,x/a)*np.exp(-x/d)
def kick():
    n=int(.25*SR); x=np.arange(n)/SR; f=45+120*np.exp(-x*35)
    return np.sin(2*np.pi*np.cumsum(f)/SR)*np.exp(-x*14)+0.3*np.exp(-x*200)*rng.standard_normal(n)
def snare():
    n=int(.22*SR); x=np.arange(n)/SR
    return (rng.standard_normal(n)*np.exp(-x*22)*0.9+np.sin(2*np.pi*190*x)*np.exp(-x*30)*0.6)
def hat(open_=False):
    n=int((.25 if open_ else .05)*SR); x=np.arange(n)/SR
    s=np.diff(rng.standard_normal(n+1)); return s*np.exp(-x*(12 if open_ else 90))*0.35
def crash():
    n=int(2.2*SR); x=np.arange(n)/SR
    s=np.diff(rng.standard_normal(n+1)); return s*np.exp(-x*2.2)*0.5
def gtr(freqs,dur,gain=1):
    n=int(dur*SR); x=np.arange(n)/SR; s=np.zeros(n)
    for f in freqs:
        for det in (-0.004,0.004):
            ph=(x*f*(1+det))%1; s+=2*ph-1
    s=np.tanh(s*3.2/len(freqs))           # distortion
    s=np.tanh(s*1.8)
    return s*env(n,0.004,dur*0.9)*0.5*gain
def bass(f,dur):
    n=int(dur*SR); x=np.arange(n)/SR
    s=np.tanh(2.5*(np.sign(np.sin(2*np.pi*f*x))*0.5+np.sin(2*np.pi*f*x)))
    return s*env(n,0.004,dur*1.2)*0.5
E=82.41; # E2
roots={'E':E,'G':E*2**(3/12),'A':E*2**(5/12),'D':E*2**(-2/12)*2,'B':E*2**(7/12)}
prog=['E','E','G','A','E','E','D','A']        # 8-beat riff, repeats
bars=int(DUR/(beat*4))+1
drums=np.zeros(N); gt=np.zeros(N); bs=np.zeros(N)
for b in range(bars):
    t0=b*4*beat
    intro = b<1
    for s in range(8):                         # 8th notes
        tt=t0+s*beat/2
        if tt>=DUR: break
        r=roots[prog[(b*2+s//4)%8 if False else s]] if False else roots[prog[s]]
        r2=r*2
        add(gt,tt,gtr([r2,r2*1.5,r2*2],beat*0.48),0.9 if s%2==0 else 0.7)
        add(bs,tt,bass(r,beat*0.48))
        add(drums,tt,hat(open_=(s==7)),1)
    for k in (0,2.5,3,): pass
    for beat_i in range(4):
        tt=t0+beat_i*beat
        if beat_i in (0,2): add(drums,tt,kick(),1.0)
        if beat_i in (1,3): add(drums,tt,snare(),0.9)
    add(drums,t0+1.5*beat,kick(),0.8); add(drums,t0+3.5*beat,kick(),0.6)
    if b%4==0: add(drums,t0,crash(),0.9)
    # fill every 4th bar
    if b%4==3:
        for q in range(4): add(drums,t0+3*beat+q*beat/4,snare(),0.7)
mix=gt*0.8+bs*0.9+drums*0.95
# strong drop at 0: crash+kick; end hit with ring-out
add(mix,0,crash(),0.8)
tail=np.ones(N); tail[int((DUR-1.2)*SR):]=np.linspace(1,0,N-int((DUR-1.2)*SR))
fade=np.minimum(1,t/0.05)
mix=np.tanh(mix*1.3)*tail*fade
mix/=np.max(np.abs(mix))*1.05
st=np.stack([mix,np.roll(mix,60)],1)  # slight stereo widening
pcm=(st*32767).astype('<i2')
w=wave.open('rock.wav','wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes()); w.close()
