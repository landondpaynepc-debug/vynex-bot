// Development-only artwork renderer: npm install @napi-rs/canvas.
// The bot serves the committed PNGs and needs no Node dependencies.
const { createCanvas, GlobalFonts } = require('@napi-rs/canvas');
const fs = require('node:fs');
const path = require('node:path');
const out = path.join(__dirname, '..', 'assets');
fs.mkdirSync(out, { recursive: true });
if (fs.existsSync('C:/Windows/Fonts/segoeui.ttf')) {
  GlobalFonts.registerFromPath('C:/Windows/Fonts/segoeui.ttf', 'Vynex Sans');
  GlobalFonts.registerFromPath('C:/Windows/Fonts/segoeuib.ttf', 'Vynex Bold');
}

function polygon(c, points, fill, stroke) {
  c.beginPath(); points.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y)); c.closePath();
  if(fill){c.fillStyle=fill;c.fill();} if(stroke){c.strokeStyle=stroke;c.lineWidth=2;c.stroke();}
}
function mark(c, x, y, scale, fill) {
  c.save(); c.translate(x,y); c.scale(scale,scale);
  polygon(c, [[0,0],[23,7],[50,53],[77,7],[100,0],[50,88]], fill);
  polygon(c, [[28,1],[50,13],[72,1],[50,39]], fill);
  c.restore();
}
function background(c,w,h) {
  const g=c.createLinearGradient(0,0,w,h);g.addColorStop(0,'#050a13');g.addColorStop(1,'#0c1d36');
  c.fillStyle=g;c.fillRect(0,0,w,h);
  const halo=c.createRadialGradient(w*.82,h*.25,0,w*.82,h*.25,w*.55);
  halo.addColorStop(0,'#183c644d');halo.addColorStop(1,'#050a1300');c.fillStyle=halo;c.fillRect(0,0,w,h);
  for(let i=0;i<7;i++){
    c.strokeStyle=i===2?'#3f83d144':'#4774ac16';c.lineWidth=i===2?2:1;
    c.beginPath();c.moveTo(w*.63+i*88,-70);c.lineTo(w*.39+i*88,h+70);c.stroke();
  }
}
function header(kind,title) {
  const canvas=createCanvas(1440,440),c=canvas.getContext('2d');background(c,1440,440);
  c.save();c.translate(1040,170);c.rotate(-.14);
  const cards=[[-110,-148,365,230],[-55,-25,365,230]];
  for(const [x,y,w,h] of cards){
    c.fillStyle='#091323';c.strokeStyle='#28466d';c.lineWidth=2;c.beginPath();c.roundRect(x,y,w,h,18);c.fill();c.stroke();
    c.fillStyle='#1c3658';c.beginPath();c.roundRect(x+26,y+28,40,40,10);c.fill();
    c.fillStyle='#2a4161';c.fillRect(x+82,y+31,140,7);c.fillStyle='#1b2c43';c.fillRect(x+82,y+49,92,6);
    for(let i=0;i<3;i++){c.fillStyle='#14243b';c.beginPath();c.roundRect(x+26,y+100+i*34,w-52,18,4);c.fill();}
  }
  mark(c,-25,40,1.8,'#6689bd32');c.restore();
  const shade=c.createLinearGradient(620,0,1020,0);shade.addColorStop(0,'#060d18');shade.addColorStop(1,'#060d1800');
  c.fillStyle=shade;c.fillRect(0,0,1020,440);
  mark(c,66,70,.36,'#dceaff');
  c.font='bold 23px "Vynex Bold", sans-serif';c.fillStyle='#9eb3d0';c.fillText('V Y N E X   T W E A K S',120,96);
  c.font='bold 112px "Vynex Bold", sans-serif';c.fillStyle='#f4f7ff';c.fillText(title,60,253);
  c.fillStyle='#5c9eff';c.fillRect(66,292,56,4);
  c.font='25px "Vynex Sans", sans-serif';c.fillStyle='#8ba0bf';c.fillText('Optimize. Refine. Perform.',66,350);
  fs.writeFileSync(path.join(out,`vynex-${kind}.png`),canvas.toBuffer('image/png'));
}
header('community','Community.');
header('support','Support.');
const canvas=createCanvas(1440,76),c=canvas.getContext('2d');background(c,1440,76);
c.fillStyle='#78aaff';c.beginPath();c.arc(36,38,4,0,Math.PI*2);c.fill();
c.font='19px "Vynex Sans", sans-serif';c.fillStyle='#839bbd';c.fillText('V Y N E X   T W E A K S',59,45);
mark(c,1360,19,.4,'#5883bb');
fs.writeFileSync(path.join(out,'vynex-footer.png'),canvas.toBuffer('image/png'));
