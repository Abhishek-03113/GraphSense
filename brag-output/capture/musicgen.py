# Generates the launch music bed locally with MusicGen (facebook/musicgen-small).
import sys, time, torch, soundfile as sf
from transformers import AutoProcessor, MusicgenForConditionalGeneration
out, seconds, seed = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
prompt = sys.argv[4]
torch.manual_seed(seed)
proc = AutoProcessor.from_pretrained('facebook/musicgen-small')
model = MusicgenForConditionalGeneration.from_pretrained('facebook/musicgen-small')
inputs = proc(text=[prompt], padding=True, return_tensors='pt')
t = time.time()
audio = model.generate(**inputs, max_new_tokens=int(seconds * 50), do_sample=True, guidance_scale=3.5)
sr = model.config.audio_encoder.sampling_rate
sf.write(out, audio[0, 0].numpy(), sr)
print('done', out, round(time.time() - t), 's')
