"""Render from a public 95s demo, project illustration and generated narration.

Requires Python/Pillow and FFmpeg/ffprobe. No API key or running app is needed.
"""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import argparse,subprocess,json,textwrap,re,hashlib
P=argparse.ArgumentParser();P.add_argument('--source-demo',type=Path,required=True);P.add_argument('--illustration',type=Path,required=True);P.add_argument('--narration',type=Path,required=True);P.add_argument('--script',type=Path,required=True);P.add_argument('--output',type=Path,required=True);A=P.parse_args()
D=A.output.resolve();W=D/'work';W.mkdir(parents=True,exist_ok=True)
BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf';REG='/System/Library/Fonts/Supplemental/Arial.ttf'
# Override these on other platforms to use equivalent licensed local fonts.
import os
BOLD=os.getenv('AMBI_DEMO_BOLD_FONT',BOLD);REG=os.getenv('AMBI_DEMO_FONT',REG)
INK='#142927';TEAL='#008D83';MUTED='#526A67';PALE='#EDF6F3'
def f(n,b=False):return ImageFont.truetype(BOLD if b else REG,n)
def run(c):
 p=subprocess.run([str(x) for x in c],capture_output=True,text=True)
 if p.returncode:raise RuntimeError(p.stderr[-3000:])
 return p.stdout

def image_base(label):
 im=Image.new('RGB',(1920,1080),'white');d=ImageDraw.Draw(im)
 d.ellipse((72,38,88,54),fill=TEAL);d.text((101,25),'ambi',font=f(36,True),fill=INK)
 d.text((1350,37),'LONDON CODEX COMMUNITY',font=f(21),fill=MUTED)
 d.line((72,90,1848,90),fill='#DFEBE8',width=2);d.text((75,119),label,font=f(22,True),fill=TEAL)
 d.line((72,1025,1848,1025),fill='#DFEBE8',width=1)
 d.text((74,1042),'Working prototype · Edited recorded task excerpts',font=f(19),fill=MUTED)
 d.text((1390,1042),'AI-generated OpenAI narration',font=f(19),fill=MUTED)
 return im,d
# Real UI excerpts are cropped out of the public extended demo, removing its editorial frame.
for name,ss,length,crop in [('mac',21.2,6.1,'crop=976:636:470:270'),('windows',40,12,'crop=1134:636:392:270,setpts=PTS/1.25,fps=30'),('stop',64.2,5,'crop=1134:636:392:270')]:
 run(['ffmpeg','-y','-v','error','-ss',ss,'-i',A.source_demo,'-t',length,'-vf',crop+',setsar=1','-an','-c:v','libx264','-preset','veryfast','-crf','19',W/f'{name}.mp4'])
art=Image.open(A.illustration).convert('RGBA');art.thumbnail((710,710))
for sid,label in [('01','OPEN SOURCE · MIT LICENSED'),('02','POWERED BY OPENAI · MAC + WINDOWS'),('03','VISIBLE ACTIONS · A VISIBLE STOP CONTROL'),('04','BUILDING IN THE OPEN')]:
 im,d=image_base(label)
 if sid=='01':
  d.text((100,270),'Meet Ambi.',font=f(114,True),fill=INK)
  d.text((108,422),'An open-source AI agent.',font=f(44),fill=MUTED)
  d.text((108,557),'London Codex Community Hackathon',font=f(32,True),fill=INK)
  d.text((108,611),'1 November 2026',font=f(32),fill=TEAL)
  d.text((108,737),'Voice. Context. Real desktop actions.',font=f(28),fill=MUTED)
  im.paste(art,(1115,185),art)
 elif sid=='02':
  d.text((74,172),'Voice. Memory. Computer use.',font=f(65,True),fill=INK)
  for x,title in [(88,'MAC · CALCULATOR'),(1002,'WINDOWS · NOTEPAD')]:
   d.text((x+12,282),title,font=f(23,True),fill=TEAL);d.rounded_rectangle((x,330,x+828,872),radius=22,fill=PALE)
  for x,text in [(100,'Speak naturally'),(686,'Pick up saved context'),(1330,'Follow desktop actions')]:d.text((x,911),text,font=f(27,True),fill=INK)
 elif sid=='03':
  d.text((90,270),'Watch.',font=f(86,True),fill=INK);d.text((90,380),'Stop.',font=f(86,True),fill=TEAL)
  d.text((94,527),'Stay in control.',font=f(42),fill=INK)
  d.text((94,628),'Per-run computer access.',font=f(25),fill=MUTED);d.text((94,670),'A separate Stop task button.',font=f(25),fill=MUTED)
  d.rounded_rectangle((685,260,1848,930),radius=22,fill=PALE)
 else:
  d.text((100,280),'Built together.',font=f(87,True),fill=INK)
  d.text((100,392),'Open to everyone.',font=f(73,True),fill=INK)
  d.text((108,545),'Explore the code. Help shape what’s next.',font=f(34),fill=TEAL)
  # Repository invitation appears with the final spoken call to action.
  url=Image.new('RGBA',(1920,1080),(0,0,0,0));ud=ImageDraw.Draw(url)
  ud.text((108,663),'github.com/jenniferumoke/',font=f(34,True),fill=INK)
  ud.text((108,715),'ambi-openai-hackathon',font=f(34,True),fill=INK)
  url.save(W/'repository-invitation.png')
  d.text((108,804),'MIT licensed · Working prototype',font=f(26),fill=MUTED)
  im.paste(art,(1115,185),art)
 bg=W/f'{sid}-background.png';im.save(bg)
 duration={'01':6.6,'02':9.7,'03':4,'04':9.7}[sid]
 args=['ffmpeg','-y','-v','error','-loop','1','-framerate','30','-i',bg]
 vf='[0:v]format=yuv420p[b]'
 if sid=='02':
  args+=['-i',W/'mac.mp4','-i',W/'windows.mp4']
  vf+=';[1:v]scale=800:510:force_original_aspect_ratio=decrease,pad=800:510:(ow-iw)/2:(oh-ih)/2:color=0xEDF6F3,tpad=stop_mode=clone:stop_duration=20[m];[2:v]scale=800:510:force_original_aspect_ratio=decrease,pad=800:510:(ow-iw)/2:(oh-ih)/2:color=0xEDF6F3,tpad=stop_mode=clone:stop_duration=20[w];[b][m]overlay=102:346[c];[c][w]overlay=1016:346[o]'
 elif sid=='03':
  args+=['-i',W/'stop.mp4'];vf+=';[1:v]scale=1100:618,setsar=1,tpad=stop_mode=clone:stop_duration=10[s];[b][s]overlay=710:285[o]'
 elif sid=='04':
  args+=['-loop','1','-framerate','30','-i',W/'repository-invitation.png'];vf+=";[1:v]fade=t=in:st=2:d=0.35:alpha=1[url];[b][url]overlay=0:0[o]"
 else:vf+=';[b]null[o]'
 vf+=f';[o]fade=t=in:st=0:d=0.16:color=white,fade=t=out:st={duration-.16}:d=0.16:color=white,scale=in_range=auto:out_range=tv,format=yuv420p,setsar=1,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[v]'
 args+=['-filter_complex',vf,'-map','[v]','-t',duration,'-r','30','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-color_range','tv','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-an',W/f'{sid}.mp4'];run(args)
 print(sid,'rendered',flush=True)
lst=W/'timeline.txt';lst.write_text(''.join(f"file '{W/(sid+'.mp4')}'\n" for sid in ['01','02','03','04']))
run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',lst,'-c','copy',W/'visuals.mp4'])
# Fit narration only if it would exceed the 30s canvas; preserve natural pace otherwise.
length=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',A.narration]).strip())
speed=max(1,length/29.15)
run(['ffmpeg','-y','-v','error','-i',A.narration,'-af',f'atempo={speed},adelay=300|300,apad,loudnorm=I=-16:TP=-1.5:LRA=11','-t','30','-ar','48000','-ac','2','-c:a','pcm_s16le',W/'audio.wav'])
text=A.script.read_text().strip();chunks=['Meet Ambi, an open-source AI agent','built at the London Codex Community Hackathon on the first of November.','Powered by OpenAI, she brings voice and computer use together on Mac and Windows.','Useful context stays in local memory, so you can pick up where you left off.','Ask for help, watch her work, and stop a task with a click.','This is our working prototype.','Explore the code and help build what comes next.']
assert re.sub(r'\s+',' ',text)==' '.join(chunks)
# Phrase times can be supplied from an independently checked audio transcription.
timing_file=D/'phrase-timings.json'
if timing_file.exists():bounds=json.loads(timing_file.read_text())
else:
 total=sum(len(x) for x in chunks);at=.3;bounds=[]
 for chunk in chunks:
  end=at+(length/speed)*len(chunk)/total;bounds.append([at,end]);at=end
args=['ffmpeg','-y','-v','error','-i',W/'visuals.mp4','-i',W/'audio.wav'];vf='[0:v]null[c0]';srt=[]
def stamp(s):
 n=round(s*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'
for j,(chunk,(start,end)) in enumerate(zip(chunks,bounds)):
 start=max(.15,start);end=min(29.6,end)
 cap=Image.new('RGBA',(1920,1080),(0,0,0,0));d=ImageDraw.Draw(cap);lines=textwrap.wrap(chunk,87)
 top=1016-(len(lines)*35+15);d.rounded_rectangle((180,top-3,1740,1020),radius=13,fill=(255,255,255,248),outline='#DCECE7',width=1)
 for k,line in enumerate(lines):tw=d.textlength(line,font=f(31));d.text(((1920-tw)/2,top+k*35),line,font=f(31),fill=INK)
 p=W/f'caption-{j}.png';cap.save(p);idx=args.count('-i');args+=['-loop','1','-framerate','30','-i',p]
 vf+=f";[c{j}][{idx}:v]overlay=0:0:enable='between(t,{start},{end})'[c{j+1}]"
 srt.append(f'{j+1}\n{stamp(start)} --> {stamp(end)}\n'+'\n'.join(lines)+'\n')
vf+=f';[c{len(chunks)}]format=yuv420p,setsar=1[v]'
args+=['-filter_complex',vf,'-map','[v]','-map','1:a:0','-t','30','-r','30','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-color_range','tv','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-c:a','aac','-b:a','160k','-ar','48000','-movflags','+faststart',D/'Ambi-Hackathon-30s.mp4'];run(args)
(D/'captions.srt').write_text('\n'.join(srt))
(D/'edit-manifest.json').write_text(json.dumps({'duration':30,'chapters':[[0,6.6,'Hackathon origin'],[6.6,16.3,'Voice, local memory and desktop examples'],[16.3,20.3,'Visible control and Stop'],[20.3,30,'Prototype and open-source invitation']],'narrationSeconds':length,'narrationTempo':speed,'illustration':A.illustration.name,'footageSource':A.source_demo.name,'source_sha256':hashlib.sha256(A.source_demo.read_bytes()).hexdigest(),'eventContext':'London Codex Community hackathon, 1 November 2026, supplied by project owner','captionTiming':'Phrase-level timing checked against captured narration; spelling is the verified requested script'},indent=2))
print('COMPLETE 30 seconds',flush=True)
