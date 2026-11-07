#!/usr/bin/env python3
"""Post-proceso: agrega a un visor 3D autocontenido un botón 'Ver site en Google Earth'
que descarga un KML (embebido como data URI) con el polígono del site.
Extrae el polígono (const SITE=... o GEO={...}) y el EPSG del propio HTML,
convierte UTM->lonlat y genera el KML.
Uso: add_earth_button.py <html> [kml_name]
"""
import sys, os, json, re, base64, subprocess

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

def gen_kml(name, lonlats, is_point):
    if is_point:
        lon, lat = lonlats[0]
        geom = f"<Point><coordinates>{lon},{lat},0</coordinates></Point>"
    else:
        coords = " ".join(f"{lon},{lat},0" for lon, lat in lonlats)
        geom = (f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}"
                f"</coordinates></LinearRing></outerBoundaryIs></Polygon>")
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
            f'<name>{name}</name>\n<Placemark>\n<name>{name}</name>\n'
            f'<Style><LineStyle><color>ff4e5aff</color><width>2</width></LineStyle>'
            f'<PolyStyle><color>3d4e5aff</color></PolyStyle></Style>\n'
            f'{geom}\n</Placemark>\n</Document>\n</kml>')

def main():
    html_path = sys.argv[1]
    kml_name = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(html_path).replace('.html', '.kml')
    html = open(html_path, encoding='utf-8').read()
    m = re.search(r'EPSG:(\d+)', html)
    epsg = int(m.group(1)) if m else 32719
    ring, src = extract_polygon(html)
    if ring is None:
        print(f'NO_POLIGONO {html_path}')
        return
    lonlats = utm_to_lonlat(ring, epsg)
    title = (re.search(r'<title>([^<]+)</title>', html) or [None, kml_name])[1]
    is_point = len(ring) == 1
    kml = gen_kml(title, lonlats, is_point)
    b64 = base64.b64encode(kml.encode()).decode()
    btn = (f'<a id="earthbtn" download="{kml_name}" '
           f'href="data:application/vnd.google-earth.kml+xml;base64,{b64}" '
           f'style="position:fixed;bottom:16px;right:16px;z-index:9;background:#0f6b3c;color:#fff;'
           f'border:1px solid #1f8f56;border-radius:8px;padding:8px 14px;text-decoration:none;'
           f'font:600 13px -apple-system,Segoe UI,Roboto,sans-serif;letter-spacing:.2px;'
           f'box-shadow:0 2px 8px rgba(0,0,0,.4)">Ver site en Google Earth</a>')
    # inyectar antes de </body> (o al final si no hay)
    if '</body>' in html:
        html = html.replace('</body>', btn + '</body>', 1)
    else:
        html += btn
    open(html_path, 'w', encoding='utf-8').write(html)
    print(f'OK {os.path.basename(html_path)} | EPSG {epsg} | {src} {len(ring)} vtx | kml {len(kml)} B')

if __name__ == '__main__':
    main()
