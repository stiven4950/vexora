# Objetos de Halloween

Treinta objetos de neón (calabaza, fantasma, calavera, murciélagos, telarañas, portal, sigilo
rúnico...) para la temporada `halloween` (`configs/seasons.yaml`, momentos con `sprite:`).

Salen de la hoja original del paquete `halloween_glowing_assets` (`preview/original_labeled_sheet.png`),
no de sus PNG sueltos: esos venían recortados con una caja fija (dibujos cortados en un borde) y
con halos oscuros. Cada archivo es solo la luz del dibujo sobre negro: `sprite_fx` la suma sobre el
video (el negro no se ve). Para regenerarlos o sacar los de otra hoja: `tools/sprites_from_sheet.py`.

Cómo se mueven en el video lo dice cada momento (`motion`): pop, rise, fly, spin, sway, fade,
floor, flat, above, hat, corner, orient (ver `engine/sprite.py`).
