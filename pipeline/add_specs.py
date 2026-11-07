#!/usr/bin/env python3
"""Post-proceso: inyecta un panel de especificaciones técnicas (bullets) en un visor 3D.
Los datos salen del dict SPECS, mapeado por nombre de archivo. Fuente de cada dato: la FICHA.md
del proyecto (no se inventa; donde no hay dato no se escribe).
Reemplaza un panel 'specs' previo si existe.
Uso: add_specs.py <html>
"""
import sys, os, re

SPECS = {
    'valparaiso.html': [
        '300 MW (SAC)',
        'Power Land \u2192 RTB',
        'Time-to-power 3 meses \u00b7 RTB 12 meses',
        'Venta 100% del capital de la SPA',
    ],
    'monterrey.html': [
        '1.125 MVA (3 \u00d7 375 MVA)',
        'Power Land (land+power \u00b7 358,6 ha)',
        'COD Fase 1: dic-2028 (unifilar)',
        'Fases 2 y 3: nueva solicitud CENACE',
    ],
    'chilcas.html': [
        '100 MW (indicativo \u00b7 +100 MW/a\u00f1o)',
        'PRDZ (Power-Ready Development Zone)',
        'Time-to-power ~2 a\u00f1os',
        'Energ\u00eda desde 2029 \u00b7 SE Chilca 220 kV',
    ],
    'llayllay.html': [
        '20 MW (Edge-AI)',
        'RTB',
        'Time-to-power 6 meses \u00b7 RTB 12 meses',
        'Permiso de edificaci\u00f3n \u2264 mar-2028',
    ],
    'durango.html': [
        '300 MW (250 MW IT \u00b7 PUE 1,20)',
        'PRDZ con capacidad reservada',
        'RTB no es entregable del vendedor',
        'S/E JOM \u00b7 LT 230 kV (8,66 km)',
    ],
    'queretaro.html': [
        '400 MW (centro de carga CENACE)',
        'Power Land (S/E 400 kV privada)',
        'Contrato de conexi\u00f3n CFE firmado',
        '~100 ha parque industrial',
    ],
    'algarrobo.html': [
        '~25 ha \u00b7 5 lotes',
        'Subdivisi\u00f3n predial (Art. 55 LGUC)',
        'Zona ZEDU (m\u00edn. 5 ha/lote)',
        'Haras Fortaleza \u00b7 Algarrobo',
    ],
    'pichilemu.html': [
        '10,47 ha',
        'Lote A \u00b7 rol 1701-3',
        'Proyecto Chacurra',
        'Frente al Oc\u00e9ano Pac\u00edfico',
    ],
    'mid.html': [
        '44,99 ha \u00b7 8 lotes',
        'Distrito de innovaci\u00f3n (5 recintos)',
        'Camino El Noviciado \u00b7 Pudahuel',
        'PRMS \u00b7 uso mixto',
    ],
}

def build_panel(bullets):
    items = '\n'.join(f'<li>{b}</li>' for b in bullets)
    return (
        '<!--SPECS-->\n'
        '<div id="specs" style="position:fixed;bottom:14px;left:14px;z-index:5;'
        'background:rgba(14,19,26,.85);backdrop-filter:blur(8px);border:1px solid #2b3440;'
        'border-radius:12px;padding:10px 14px;font-size:12px;max-width:340px;color:#dfe6ee">\n'
        '<div style="font-weight:700;color:#ff5a4e;font-size:10px;letter-spacing:.6px;'
        'margin-bottom:4px">ESPECIFICACIONES</div>\n'
        f'<ul style="margin:0;padding-left:16px;line-height:1.55">{items}</ul>\n'
        '</div>\n'
        '<!--/SPECS-->'
    )

def main():
    html_path = sys.argv[1]
    name = os.path.basename(html_path)
    bullets = SPECS.get(name)
    if not bullets:
        print(f'NO_SPECS {name}')
        return
    html = open(html_path, encoding='utf-8').read()
    # quitar panel previo
    html = re.sub(r'<!--SPECS-->.*?<!--/SPECS-->\n?', '', html, flags=re.DOTALL)
    panel = build_panel(bullets)
    if '<div id="tip" hidden></div>' in html:
        html = html.replace('<div id="tip" hidden></div>', panel + '\n<div id="tip" hidden></div>', 1)
    else:
        html = html.replace('</body>', panel + '\n</body>', 1)
    open(html_path, 'w', encoding='utf-8').write(html)
    print(f'OK {name} | {len(bullets)} bullets')

if __name__ == '__main__':
    main()
