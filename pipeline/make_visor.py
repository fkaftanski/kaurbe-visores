#!/usr/bin/env python3
"""Pipeline genérico de visor 3D autocontenido (Three.js + OrbitControls, sin CDN).
Uso: make_visor.py <config.json>
config.json: {name, title, subtitle, epsg, zoom, box_m, site_name, site_sub,
              site_ring: [[lon,lat],...], pois: [{n, lon, lat}], out}
"""
import sys, os, json, math, re, subprocess, glob, urllib.request
import numpy as np
from PIL import Image

UA = 'KAURBE-IT visor/1.0 (contacto@kaurbe.com)'

def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print('ERR:', cmd[:130], '|', r.stderr[:250])
    return r

def utm(lon, lat, epsg):
    out = sh(f'echo "{lon} {lat}" | gdaltransform -s_srs EPSG:4326 -t_srs EPSG:{epsg}').stdout.strip().split()
    return float(out[0]), float(out[1])

def copernicus(lat, lon):
    ns = 'N' if lat >= 0 else 'S'
    ew = 'E' if lon >= 0 else 'W'
    a = abs(int(math.floor(lat))); o = abs(int(math.floor(lon)))
    return f'{ns}{a:02d}_00_{ew}{o:03d}_00'

def download_dem(lat, lon, dem_tif):
    if os.path.exists(dem_tif) and os.path.getsize(dem_tif) > 1_000_000:
        return
    t = copernicus(lat, lon)
    url = f'https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{t}_DEM/Copernicus_DSM_COG_10_{t}_DEM.tif'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    data = urllib.request.urlopen(req, timeout=120).read()
    open(dem_tif, 'wb').write(data)
    print('DEM', t, len(data) // 1024, 'KB')

def tile_xy(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y

def download_tiles(lon0, lat1, lon1, lat0, z, outdir):
    x0, y0 = tile_xy(lat1, lon0, z); x1, y1 = tile_xy(lat0, lon1, z)
    os.makedirs(outdir, exist_ok=True)
    print(f'z{z} x {x0}..{x1} y {y0}..{y1} -> {(x1-x0+1)*(y1-y0+1)} teselas')
    url = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
    ok = fail = 0
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            p = f'{outdir}/{x}_{y}.jpg'
            if os.path.exists(p) and os.path.getsize(p) > 2000:
                ok += 1; continue
            u = url.format(z=z, y=y, x=x)
            for attempt in range(4):
                try:
                    req = urllib.request.Request(u, headers={'User-Agent': UA, 'Accept': 'image/*'})
                    open(p, 'wb').write(urllib.request.urlopen(req, timeout=30).read())
                    ok += 1; break
                except Exception as e:
                    if attempt == 3:
                        fail += 1; print('  FAIL', x, y, e)
    print('ok', ok, 'fail', fail)

def build_assets(cfg, wd):
    epsg = cfg['epsg']; z = cfg['zoom']
    ring_utm = [utm(lon, lat, epsg) for lon, lat in cfg['site_ring']]
    xs = [p[0] for p in ring_utm]; ys = [p[1] for p in ring_utm]
    if cfg.get('box_c'):
        cx, cy = cfg['box_c']
    else:
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    m = cfg['box_m'] / 2
    E0, E1 = cx - m, cx + m
    Nn, Ns = cy + m, cy - m
    W, H = E1 - E0, Nn - Ns
    clon, clat = cfg['clon'], cfg['clat']
    print(f'box {W:.0f} m | E {E0:.0f}..{E1:.0f} N {Ns:.0f}..{Nn:.0f}')
    # DEM
    dem_tif = os.path.join(wd, 'dem.tif')
    download_dem(clat, clon, dem_tif)
    dem_utm = os.path.join(wd, 'dem_utm.tif')
    tr = max(8, round(W / 320))
    sh(f'gdalwarp -q -t_srs EPSG:{epsg} -tr {tr} {tr} -te {E0} {Ns} {E1} {Nn} -r bilinear -overwrite "{dem_tif}" "{dem_utm}"')
    dem_bin = os.path.join(wd, 'dem.bin')
    sh(f'gdal_translate -q -ot Float32 -of ENVI "{dem_utm}" "{dem_bin}"')
    _info = sh(f'gdalinfo "{dem_utm}"').stdout
    _m = re.search(r'Size is (\d+), (\d+)', _info)
    GW, GH = int(_m.group(1)), int(_m.group(2))
    dem = np.fromfile(dem_bin, dtype=np.float32).reshape(GH, GW)
    v = dem[(dem > -1000) & (dem < 9000)]
    mean = v.mean() if len(v) else 0
    dem = np.where(dem < -1000, mean, dem); dem = np.nan_to_num(dem, nan=mean)
    zmin = float(dem.min()); zmax = float(dem.max())
    dem.astype('<f4').tofile(os.path.join(wd, 'dem_grid.f32'))
    print(f'DEM {dem.shape} z {zmin:.0f}..{zmax:.0f}')
    orto_local = cfg.get('orto_local')
    if orto_local:
        # ortomosaico/dron local (GeoTIFF georreferenciado) en vez de tiles Esri
        res = round(W / 2400, 3)
        sat = os.path.join(wd, 'sat_utm.tif')
        sh(f'gdalwarp -q -t_srs EPSG:{epsg} -tr {res} {res} -te {E0} {Ns} {E1} {Nn} -r bilinear -overwrite "{orto_local}" "{sat}"')
    else:
        # tiles -> lonlat box
        def utm2lonlat(e, n):
            out = sh(f'echo "{e} {n}" | gdaltransform -s_srs EPSG:{epsg} -t_srs EPSG:4326').stdout.strip().split()
            return float(out[0]), float(out[1])
        lon0, lat_n = utm2lonlat(E0, Nn)
        lon1, lat_s = utm2lonlat(E1, Ns)
        tdir = os.path.join(wd, 'tiles')
        download_tiles(min(lon0, lon1), max(lat_n, lat_s), max(lon0, lon1), min(lat_n, lat_s), z, tdir)
        # mosaico
        n = 2 ** z
        def tlon(x): return x / n * 360.0 - 180.0
        def tlat(y): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        ldir = os.path.join(wd, 'tiles_wld'); os.makedirs(ldir, exist_ok=True)
        lines = []
        for t in sorted(glob.glob(os.path.join(tdir, '*.jpg'))):
            b = os.path.basename(t); x = int(b.split('_')[0]); y = int(b.split('_')[1].split('.')[0])
            lonw, lone, latn, lats = tlon(x), tlon(x + 1), tlat(y), tlat(y + 1)
            A = (lone - lonw) / 256.0; D = -(latn - lats) / 256.0
            E = lonw + A / 2.0; F = latn + D / 2.0
            dst = os.path.join(ldir, b)
            if not os.path.exists(dst): os.link(t, dst)
            open(dst.replace('.jpg', '.wld'), 'w').write(f"{A:.16f}\n0\n0\n{D:.16f}\n{E:.16f}\n{F:.16f}\n")
            lines.append(dst)
        lst = os.path.join(wd, 'tiles_list.txt')
        open(lst, 'w').write('\n'.join(lines) + '\n')
        vrt = os.path.join(wd, 'mosaic.vrt')
        sh(f'gdalbuildvrt -q -a_srs EPSG:4326 -input_file_list "{lst}" "{vrt}"')
        sat = os.path.join(wd, 'sat_utm.tif')
        res = round(156543.03 * math.cos(math.radians(clat)) / n, 3)
        sh(f'gdalwarp -q -t_srs EPSG:{epsg} -tr {res} {res} -te {E0} {Ns} {E1} {Nn} -r bilinear -overwrite "{vrt}" "{sat}"')
    info = sh(f'gdalinfo "{sat}"').stdout
    for line in info.splitlines():
        if 'Size is' in line: print(' ', line.strip())
    orto = os.path.join(wd, 'orto_tex.jpg')
    sh(f'gdal_translate -q -of JPEG -co QUALITY=85 "{sat}" "{orto}"')
    TW = int(round(W / res)); TH = int(round(H / res))
    mask = Image.new('L', (TW, TH), 255).resize((1024, round(1024 * TH / TW)), Image.Resampling.BILINEAR)
    mask.save(os.path.join(wd, 'alpha_mask.png'), optimize=True)
    meta = {'E0': E0, 'N0': Nn, 'W': W, 'H': H, 'GW': GW, 'GH': GH,
            'zmin': zmin, 'zmax': zmax, 'TW': TW, 'TH': TH, 'res': res}
    json.dump(meta, open(os.path.join(wd, 'grid_meta.json'), 'w'))
    # GEO (UTM)
    def _to_ll(lon, lat):
        e, n = utm(lon, lat, epsg)
        return [round(e, 2), round(n, 2)]
    geo = {
        'site': [[round(p[0], 2), round(p[1], 2)] for p in ring_utm],
        'pois': [{'n': p['n'], 'e': round(utm(p['lon'], p['lat'], epsg)[0], 2), 'nn': round(utm(p['lon'], p['lat'], epsg)[1], 2)} for p in cfg.get('pois', [])],
        'lines': [{'n': l['n'], 'color': l.get('color', '#27d3ff'), 'pts': [_to_ll(lon, lat) for lon, lat in l['pts']]} for l in cfg.get('lines', [])],
        'polygons': [{'n': p['n'], 'color': p.get('color', '#f0a020'), 'ring': [_to_ll(lon, lat) for lon, lat in p['ring']]} for p in cfg.get('polygons', [])],
    }
    json.dump(geo, open(os.path.join(wd, 'geo.json'), 'w'))
    return meta, geo

def gen_html(cfg, wd, meta, geo, out):
    three = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'three.min.js')).read()
    orbit = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'OrbitControls.js')).read()
    def b64(f):
        import base64
        return base64.b64encode(open(os.path.join(wd, f), 'rb').read()).decode()
    E0, N0, W, H, GW, GH, zmin, TW, TH = (meta[k] for k in ('E0', 'N0', 'W', 'H', 'GW', 'GH', 'zmin', 'TW', 'TH'))
    title = cfg['title']; subtitle = cfg['subtitle']
    site_name = cfg.get('site_name', ''); site_sub = cfg.get('site_sub', '')
    pois_js = json.dumps(geo['pois'], separators=(',', ':'))
    site_js = json.dumps(geo['site'], separators=(',', ':'))
    lines_js = json.dumps(geo.get('lines', []), separators=(',', ':'))
    polygons_js = json.dumps(geo.get('polygons', []), separators=(',', ':'))
    html = f'''<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
html,body{{margin:0;height:100%;overflow:hidden;background:#0e131a;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#fff}}
#c{{position:fixed;inset:0}}
.pn{{position:absolute;background:rgba(14,19,26,.85);backdrop-filter:blur(8px);border:1px solid #2b3440;border-radius:12px;padding:12px 14px;font-size:13px;z-index:5}}
#hud{{top:14px;left:14px;max-width:340px}}
#hud h1{{margin:0;font-size:20px;font-weight:700;letter-spacing:-.3px}}
#hud .mut{{color:#8f9aa8;margin-top:3px}}
#hud .x{{font-size:11px}}
#layers{{top:14px;right:14px;min-width:150px}}
#layers summary{{cursor:pointer;font-weight:700}}
#layers label{{display:block;margin:5px 0;cursor:pointer}}
#legend{{bottom:14px;left:14px;max-width:300px}}
#legend h2{{margin:0 0 6px;font-size:14px}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-2px}}
.btns button{{background:#1c2530;color:#fff;border:1px solid #2b3440;border-radius:8px;padding:6px 12px;margin-right:6px;cursor:pointer}}
#hint{{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);color:#9fb0c0;font-size:12px;z-index:4;background:rgba(14,19,26,.7);padding:6px 12px;border-radius:20px;pointer-events:none}}
#north{{position:absolute;top:14px;left:50%;transform:translateX(-50%);width:44px;height:44px;z-index:5}}
#tip{{position:absolute;z-index:6;background:rgba(12,16,22,.92);border:1px solid #2b3440;border-radius:8px;padding:6px 9px;font-size:12px;pointer-events:none}}
#load{{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:#0e131a;z-index:9;font-size:15px;color:#8f9aa8}}
</style></head><body>
<div id="c"></div>
<div id="load">Cargando modelo…</div>
<div id="hint">Arrastra para rotar · rueda o pellizco para zoom · clic derecho para desplazar</div>
<svg id="north" viewBox="-22 -22 44 44"><g id="nrot"><circle r="20" fill="rgba(14,19,26,.8)" stroke="#2b3440"/>
<path d="M0,-15 L6,4 L0,0 L-6,4Z" fill="#ff5a4e"/><path d="M0,15 L6,4 L0,0 L-6,4Z" fill="#6b7787"/>
<text y="-4" x="0" font-size="7" fill="#fff" text-anchor="middle" font-weight="700" transform="translate(0,-11)">N</text></g></svg>
<div id="hud" class="pn">
 <h1>{title}</h1>
 <div class="mut">{subtitle}</div>
 <div class="mut x">{site_name} · {site_sub}</div>
 <div class="mut x">{cfg.get('orto_label','Ortofoto satelital Esri')} · Relieve Copernicus GLO-30 · UTM (EPSG:{cfg['epsg']})</div>
</div>
<details id="layers" class="pn" open><summary>Capas</summary>
 <label><input type="checkbox" id="k_orto" checked>Ortofoto</label>
 <label><input type="checkbox" id="k_site" checked>Predio</label>
 <label><input type="checkbox" id="k_pois" checked>Puntos</label>
 <label><input type="checkbox" id="k_conn" checked>Conexión</label>
 <label><input type="checkbox" id="k_lab" checked>Etiquetas</label>
 <div class="mut" style="margin-top:4px">Exageración vertical <span id="exv"></span></div>
 <input type="range" id="ex" min="1" max="3" step="0.1" value="1.8">
 <div class="btns"><button id="b3d">Vista 3D</button><button id="btop">Cenital</button></div>
</details>
<div id="tip" hidden></div>
<script>{three}</script>
<script>{orbit}</script>
<script>
const META={json.dumps(meta, separators=(',', ':'))};
const SITE={site_js};
const POIS={pois_js};
const LINES={lines_js};
const POLYGONS={polygons_js};
const DEMB64="{b64('dem_grid.f32')}";
const ORTO="data:image/jpeg;base64,{b64('orto_tex.jpg')}";
const MASK="data:image/png;base64,{b64('alpha_mask.png')}";
const {{E0,N0,W,H,GW,GH,zmin,TW,TH}}=META;
const dem=new Float32Array(Uint8Array.from(atob(DEMB64),c=>c.charCodeAt(0)).buffer);
let EX=1.8;
const SC=Math.max(1, W/3000);
const X=E=>E-E0, Z=N=>N0-N;
function hRaw(x,z){{const fx=Math.min(Math.max(x/W*(GW-1),0),GW-1.001), fz=Math.min(Math.max(z/H*(GH-1),0),GH-1.001);
 const j=Math.floor(fx), i=Math.floor(fz), u=fx-j, v=fz-i, a=dem[i*GW+j], b=dem[i*GW+j+1], c=dem[(i+1)*GW+j], d=dem[(i+1)*GW+j+1];
 return a*(1-u)*(1-v)+b*u*(1-v)+c*(1-u)*v+d*u*v;}}
const hY=(x,z)=>(hRaw(x,z)-zmin)*EX;
const HASGL=(()=>{{try{{const c=document.createElement('canvas');return !!(window.WebGLRenderingContext&&(c.getContext('webgl2')||c.getContext('webgl')));}}catch(e){{return false;}}}})();
if(!HASGL){{document.querySelectorAll('.pn,#north,#load,#hint').forEach(e=>e.style.display='none');
 const d=document.createElement('div'); d.id='nogl';
 d.innerHTML='<p><b>Este visor necesita WebGL.</b></p><p>Ábrelo en Chrome, Edge o Safari.</p>';
 document.body.appendChild(d);}} else {{
const renderer=new THREE.WebGLRenderer({{antialias:true,alpha:true}});
renderer.setPixelRatio(Math.min(window.devicePixelRatio,2)); renderer.setSize(innerWidth,innerHeight);
renderer.outputEncoding=THREE.sRGBEncoding; document.getElementById('c').appendChild(renderer.domElement);
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(42,innerWidth/innerHeight,1,20000);
const controls=new THREE.OrbitControls(camera,renderer.domElement);
controls.enableDamping=true; controls.dampingFactor=.08; controls.maxPolarAngle=Math.PI*.47; controls.minDistance=60; controls.maxDistance=30000;
scene.add(new THREE.HemisphereLight(0xffffff,0x8a8f96,.82));
const sun=new THREE.DirectionalLight(0xffffff,.32); sun.position.set(-600,900,-300); scene.add(sun);
const ANI=renderer.capabilities.getMaxAnisotropy();
const tg=new THREE.BufferGeometry(), pos=new Float32Array(GW*GH*3), uv=new Float32Array(GW*GH*2), idx=[];
for(let i=0;i<GH;i++)for(let j=0;j<GW;j++){{const k=i*GW+j; pos[k*3]=j/(GW-1)*W; pos[k*3+2]=i/(GH-1)*H; uv[k*2]=j/(GW-1); uv[k*2+1]=1-i/(GH-1);}}
for(let i=0;i<GH-1;i++)for(let j=0;j<GW-1;j++){{const a=i*GW+j,b=a+1,c=a+GW,d=c+1; idx.push(a,c,b,b,c,d);}}
tg.setIndex(idx); tg.setAttribute('position',new THREE.BufferAttribute(pos,3)); tg.setAttribute('uv',new THREE.BufferAttribute(uv,2));
function setTerrainY(){{for(let k=0;k<GW*GH;k++)pos[k*3+1]=(dem[k]-zmin)*EX; tg.attributes.position.needsUpdate=true; tg.computeVertexNormals(); tg.computeBoundingSphere();}}
const ortoTex=new THREE.TextureLoader().load(ORTO,()=>{{const L=document.getElementById('load'); L.style.opacity=0; setTimeout(()=>L.remove(),600);}}); ortoTex.encoding=THREE.sRGBEncoding; ortoTex.anisotropy=ANI;
const maskTex=new THREE.TextureLoader().load(MASK);
const tmat=new THREE.MeshLambertMaterial({{map:ortoTex,color:0xffffff,alphaMap:maskTex,alphaTest:.5}});
const terrain=new THREE.Mesh(tg,tmat); scene.add(terrain);
function overlay(draw, grp){{const cv=document.createElement('canvas'); cv.width=TW; cv.height=TH; const g=cv.getContext('2d');
 const s=TW/W; g.setTransform(s,0,0,s,0,0); draw(g); const t=new THREE.CanvasTexture(cv); t.anisotropy=ANI; t.encoding=THREE.sRGBEncoding;
 const m=new THREE.Mesh(tg,new THREE.MeshBasicMaterial({{map:t,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2}}));
 m.renderOrder=2; (grp||scene).add(m); return m;}}
const path=(g,r)=>{{g.beginPath(); r.forEach((p,i)=>i?g.lineTo(X(p[0]),Z(p[1])):g.moveTo(X(p[0]),Z(p[1]))); g.closePath();}};
const siteOv=overlay(g=>{{path(g,SITE); g.fillStyle='rgba(255,91,78,.16)'; g.fill(); g.lineJoin='round';
 path(g,SITE); g.strokeStyle='rgba(0,0,0,.55)'; g.lineWidth=2.6; g.stroke(); g.strokeStyle='#ff5a4e'; g.lineWidth=1.4; g.stroke();}});
function drape(ring,step){{const out=[]; for(let i=0;i<ring.length-1;i++){{const a=ring[i],b=ring[i+1]; const L=Math.hypot(b[0]-a[0],b[1]-a[1]); const n=Math.max(1,Math.ceil(L/step));
 for(let s=0;s<n;s++){{const t=s/n, x=X(a[0]+(b[0]-a[0])*t), z=Z(a[1]+(b[1]-a[1])*t); out.push(new THREE.Vector3(x,hY(x,z)+1.2*EX,z));}}}} out.push(out[0].clone()); return out;}}
function drapeLine(ring,step){{const out=[]; for(let i=0;i<ring.length-1;i++){{const a=ring[i],b=ring[i+1]; const L=Math.hypot(b[0]-a[0],b[1]-a[1]); const n=Math.max(1,Math.ceil(L/step)); for(let s=0;s<n;s++){{const t=s/n, x=X(a[0]+(b[0]-a[0])*t), z=Z(a[1]+(b[1]-a[1])*t); out.push(new THREE.Vector3(x,hY(x,z)+1.4*EX,z));}}}} return out;}}
function tube(pts,r,color){{const c=new THREE.CurvePath(); for(let i=0;i<pts.length-1;i++)c.add(new THREE.LineCurve3(pts[i],pts[i+1]));
 return new THREE.Mesh(new THREE.TubeGeometry(c,pts.length*2,r,8,false),new THREE.MeshBasicMaterial({{color}}));}}
const siteG=new THREE.Group(), poisG=new THREE.Group(), labG=new THREE.Group(); scene.add(siteG,poisG,labG);
const netG=new THREE.Group(); scene.add(netG);
function label(lines,color,big){{const dpr=2, h=big?96:64; const mm=document.createElement('canvas').getContext('2d'); let w;
 if(big){{mm.font='700 38px -apple-system,Segoe UI,Roboto,sans-serif'; const w1=mm.measureText(lines[0]).width; mm.font='600 28px -apple-system,Segoe UI,Roboto,sans-serif'; const w2=mm.measureText(lines[1]).width; w=Math.ceil(Math.max(w1,w2))+48;}}
 else {{mm.font='800 40px -apple-system,Segoe UI,Roboto,sans-serif'; w=Math.max(150,Math.ceil(mm.measureText(lines[0]).width)+44);}}
 const cv=document.createElement('canvas'); cv.width=w*dpr; cv.height=h*dpr;
 const g=cv.getContext('2d'); g.scale(dpr,dpr); g.fillStyle='rgba(12,16,22,.88)'; const r=10;
 g.beginPath(); g.moveTo(r,0); g.arcTo(w,0,w,h,r); g.arcTo(w,h,0,h,r); g.arcTo(0,h,0,0,r); g.arcTo(0,0,w,0,r); g.fill();
 g.fillStyle=color; g.fillRect(0,0,big?6:0,h); g.textAlign='center'; g.fillStyle='#fff';
 if(big){{g.font='700 38px -apple-system,Segoe UI,Roboto,sans-serif'; g.fillText(lines[0],w/2+3,42); g.font='600 28px -apple-system,Segoe UI,Roboto,sans-serif';
 g.fillStyle='#d6dde6'; g.fillText(lines[1],w/2+3,82);}} else {{g.font='800 40px -apple-system,Segoe UI,Roboto,sans-serif'; g.fillStyle=color; g.fillText(lines[0],w/2,44);}}
 const t=new THREE.CanvasTexture(cv); t.encoding=THREE.sRGBEncoding; t.anisotropy=ANI;
 const sp=new THREE.Sprite(new THREE.SpriteMaterial({{map:t,depthTest:false,transparent:true}})); sp.renderOrder=10; sp.userData.ar=w/h; return sp;}}
// rótulo del sitio (sin conector)
const cs=SITE.reduce((a,p)=>{{a[0]+=p[0];a[1]+=p[1];return a;}},[0,0]);
const sLab=label(["{site_name}".replace(/\"/g,''), "{site_sub}".replace(/\"/g,'')],'#ff5a4e',true);
sLab.userData.p=[X(cs[0]/SITE.length),Z(cs[1]/SITE.length)]; sLab.userData.big=1; labG.add(sLab);
// POIs (esfera + rótulo con conector delgado)
const connG=new THREE.Group(); scene.add(connG);
POIS.forEach(p=>{{const x=X(p.e), z=Z(p.nn); const m=new THREE.Mesh(new THREE.SphereGeometry(5*SC,16,12),new THREE.MeshBasicMaterial({{color:0x27d3ff}})); m.position.set(x,hY(x,z)+1.5*EX,z); poisG.add(m);
 const s=label([p.n],'#27d3ff',false); s.userData.p=[x,z]; s.userData.k=30; labG.add(s);}});
function build(){{setTerrainY(); while(siteG.children.length){{const c=siteG.children.pop(); c.geometry&&c.geometry.dispose();}}
 if(SITE.length>=3) siteG.add(tube(drape(SITE,4),2.0*SC,0xff1e10));
 while(netG.children.length){{const c=netG.children.pop(); c.geometry&&c.geometry.dispose();}}
 LINES.forEach(l=>netG.add(tube(drapeLine(l.pts,20),Math.max(6,W/250),l.color)));
 POLYGONS.forEach(p=>overlay(g=>{{path(g,p.ring); g.fillStyle='rgba(240,160,32,.22)'; g.fill(); g.strokeStyle=p.color; g.lineWidth=3; g.stroke();}}, netG));
 labG.children.concat(poisG.children).forEach(s=>{{const [x,z]=s.userData.p; s.position.set(x,hY(x,z)+(s.userData.big?26:s.userData.k?30:0)*Math.max(1,EX*.7),z);}});
 rebuildConn(); document.getElementById('exv').textContent='×'+EX.toFixed(1);}}
function rebuildConn(){{while(connG.children.length){{const c=connG.children.pop(); c.geometry&&c.geometry.dispose();}}
 POIS.forEach(p=>{{const x=X(p.e), z=Z(p.nn), y=hY(x,z)+1.5*EX; const s=labG.children.find(q=>q.userData.k===30&&q.userData.p[0]===x&&q.userData.p[1]===z); if(!s)return;
  const geom=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x,y,z), s.position.clone()]);
  connG.add(new THREE.Line(geom,new THREE.LineBasicMaterial({{color:0x27d3ff,transparent:true,opacity:.55}})));}});}}
function scaleLabels(){{const f=Math.tan(camera.fov*Math.PI/360)*2/innerHeight; labG.children.concat(poisG.children).forEach(s=>{{const d=camera.position.distanceTo(s.position);
 const m=Math.min(innerWidth,innerHeight); const hpx=s.userData.big?Math.min(44,Math.max(20,m*.05)):Math.min(26,Math.max(14,m*.03)); const hw=d*f*hpx; s.scale.set(hw*s.userData.ar,hw,1);}});}}
const C=(()=>{{const x=W/2, z=H/2; return new THREE.Vector3(x,hY(x,z),z);}})();
const D3=()=>Math.max(W,H)*1.6;
let anim=null;
let fly=function(p,t){{anim={{p0:camera.position.clone(),t0:controls.target.clone(),p1:p,t1:t,s:performance.now()}};}};
function view3d(){{const d=D3(); fly(new THREE.Vector3(C.x-0.18*d,C.y+0.66*d,C.z+0.78*d),C.clone());}}
function viewTop(){{const d=Math.max(W,H)*1.35; fly(new THREE.Vector3(C.x,C.y+d,C.z+1),C.clone());}}
(()=>{{const d=D3(); camera.position.set(C.x-0.18*d,C.y+0.66*d,C.z+0.78*d); controls.target.copy(C); controls.update();}})();
const on=(id,f)=>document.getElementById(id).addEventListener('change',e=>f(e.target.checked));
on('k_orto',v=>{{tmat.map=v?ortoTex:null; tmat.color.set(v?0xffffff:0x8f9a86); tmat.needsUpdate=true;}});
on('k_site',v=>siteOv.visible=siteG.visible=v); on('k_pois',v=>{{poisG.visible=v; connG.visible=v;}}); on('k_conn',v=>netG.visible=v); on('k_lab',v=>labG.visible=v);
document.getElementById('ex').addEventListener('input',e=>{{EX=+e.target.value; build();}});
document.getElementById('b3d').onclick=view3d; document.getElementById('btop').onclick=viewTop;
const nrot=document.getElementById('nrot');
function loop(t){{requestAnimationFrame(loop);
 if(anim){{let k=Math.min(1,(t-anim.s)/1100); k=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2; camera.position.lerpVectors(anim.p0,anim.p1,k); controls.target.lerpVectors(anim.t0,anim.t1,k); if(k>=1)anim=null;}}
 controls.update(); scaleLabels();
 const dx=controls.target.x-camera.position.x, dz=controls.target.z-camera.position.z; nrot.setAttribute('transform','rotate('+(-Math.atan2(dx,-dz)*180/Math.PI)+')');
 renderer.render(scene,camera);}}
requestAnimationFrame(loop);
addEventListener('resize',()=>{{camera.aspect=innerWidth/innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth,innerHeight);}});
window.__view=v=>{{anim=null; const d=v==='top'?Math.max(W,H)*1.35:D3();
 if(v==='top')camera.position.set(C.x,C.y+d,C.z+1); else camera.position.set(C.x-0.18*d,C.y+0.66*d,C.z+0.78*d); controls.target.copy(C); controls.update();}};
(()=>{{const h=location.hash; if(h.includes('top'))window.__view('top');}})();
build();
}}
</script></body></html>'''
    open(out, 'w').write(html)
    print('HTML', out, len(html) // 1024, 'KB')

if __name__ == '__main__':
    cfg = json.load(open(sys.argv[1]))
    wd = cfg['wd']; os.makedirs(wd, exist_ok=True)
    meta, geo = build_assets(cfg, wd)
    out = os.path.join(wd, cfg['out'])
    gen_html(cfg, wd, meta, geo, out)
