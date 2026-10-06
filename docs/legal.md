# Consideraciones legales y de cumplimiento

> No es asesoramiento jurídico. Identifica riesgos y puntos que requieren revisión por un
> profesional en la jurisdicción donde se opere el servicio.

## Riesgos identificados

1. **Derechos de autor.** Facilitar copias de obras protegidas puede generar responsabilidad
   (directa o secundaria) según la jurisdicción. Mitigaciones de diseño: sin catálogo ni
   búsqueda, contenido solo público, archivos efímeros (15 min), aviso de responsabilidad
   visible, canal de retirada, capacidad de bloquear proveedores/enlaces.
2. **Medidas tecnológicas de protección.** DMCA §1201 (EE. UU.) y el art. 6 de la Directiva
   2001/29/CE (UE) prohíben eludirlas. El servicio no elude DRM, muros de pago ni
   autenticación, no genera *PO tokens* ni impersona clientes TLS. La ejecución del JS del
   reproductor de YouTube (EJS) para obtener formatos es un punto **a revisar por un
   abogado** (existió debate público en 2020 sobre youtube-dl). El proveedor se puede
   desactivar con `DL_PROVIDERS`.
3. **Términos de servicio de las plataformas.** Varias prohíben la descarga fuera de sus
   funciones oficiales. Riesgo contractual y de bloqueo de IP para el operador.
4. **Régimen de intermediarios.** DMCA §512 (safe harbor: agente designado, procedimiento
   de notificación y contranotificación, política de reincidentes) y, en la UE, la
   Digital Services Act (puntos de contacto, mecanismo de notificación y acción,
   transparencia según tamaño). A evaluar según el país del operador y del público.
5. **Privacidad (RGPD/LOPDGDD si hay usuarios en la UE).** La IP es dato personal: se usa
   de forma transitoria y anonimizada (HMAC) para seguridad (interés legítimo a documentar);
   sin cookies de seguimiento → normalmente sin banner. Revisar registro de actividades,
   base jurídica y plazos de retención con un profesional.

## Páginas incluidas (borradores propios)

`/terminos`, `/privacidad`, `/copyright`, `/uso-aceptable`. Redactadas desde cero para este
proyecto, marcadas como borrador pendiente de revisión jurídica. Falta completar la
identidad y el contacto del operador (P0).
