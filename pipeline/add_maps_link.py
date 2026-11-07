#!/usr/bin/env python3
"""Post-proceso: agrega a un visor 3D autocontenido un botón 'Ver en Google Maps'
que abre el punto (centroide del polígono del site) en Google Maps.
Extrae el polígono (const SITE=... o GEO={...}) y el EPSG del propio HTML,
convierte UTM->lonlat y genera el link a Google Maps.
Reemplaza cualquier botón 'earthbtn' previo.
Uso: add_maps_link.py <html>
"""
import sys, os, json, re, subprocess

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

def utm_to_lonlat(pairs, epsg):
    inp = "\n".join(f"{e} {n}" for e, n in pairs)
    out = sh(f"echo '{inp}' | gdaltransform -s_srs EPSG:{epsg} -t_srs EPSG:4326")
    res = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 2:
            res.append((float(p[0]), float(p[1])))
    return res

def extract_polygon(html):
    # 1) const SITE = [[...],...]
    m = re.search(r'const SITE\s*=\s*(\[\[.*?\]\])\s*;', html)
    if m:
        return json.loads(m.group(1)), 'SITE'
    # 2) GEO = {...}  o  GEO={...}
    m = re.search(r'GEO\s*=\s*(\{.*?\});', html, re.DOTALL)
    if m:
        try:
            geo = json.loads(m.group(1))
            for key in ('central', 'pos', 'desl', 'site', 'predio', 'terreno'):
                v = geo.get(key)
                if isinstance(v, list) and len(v) >= 3 and all(isinstance(x, list) and len(x) >= 2 for x in v):
                    return v, f'GEO.{key}'
        except Exception as e:
            print('  GEO parse err:', e)
    return None, None

def main():
    html_path = sys.argv[1]
    html = open(html_path, encoding='utf-8').read()
    m = re.search(r'EPSG:(\d+)', html)
    epsg = int(m.group(1)) if m else 32719
    ring, src = extract_polygon(html)
    if ring is None:
        print(f'NO_POLIGONO {html_path}')
        return
    lonlats = utm_to_lonlat(ring, epsg)
    clon = sum(p[0] for p in lonlats) / len(lonlats)
    clat = sum(p[1] for p in lonlats) / len(lonlats)
    maps_url = f'https://www.google.com/maps?q={clat:.6f},{clon:.6f}'
    btn = (f'<a id="earthbtn" href="{maps_url}" target="_blank" rel="noopener" '
           f'style="position:fixed;bottom:16px;right:16px;z-index:9;background:#0f6b3c;color:#fff;'
           f'border:1px solid #1f8f56;border-radius:8px;padding:8px 14px;text-decoration:none;'
           f'font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;letter-spacing:.2px;'
           f'box-shadow:0 2px 8px rgba(0,0,0,.4)">Ver en Google Maps</a>')
    # quitar botón previo (si existe)
    html = re.sub(r'<a id="earthbtn".*?</a>', '', html, flags=re.DOTALL)
    if '</body>' in html:
        html = html.replace('</body>', btn + '</body>', 1)
    else:
        html += btn
    open(html_path, 'w', encoding='utf-8').write(html)
    print(f'OK {os.path.basename(html_path)} | {clat:.5f},{clon:.5f} | {src} {len(ring)} vtx')

if __name__ == '__main__':
    main()
