"""Correccion reproducible de dos directivas #undef defectuosas de OneWire 2.3.8.

Solo cambia la copia generada en .pio/libdeps, no fuentes del usuario ni venv.
No se ocultan warnings: se corrige su causa sin cambiar semantica del driver.
"""
from pathlib import Path

REPLACEMENTS = {
    '#  undef noInterrupts() {portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;portENTER_CRITICAL(&mux)': '#  undef noInterrupts',
    '#  undef interrupts() portEXIT_CRITICAL(&mux);}': '#  undef interrupts',
}


def patch_onewire(path):
    path = Path(path)
    original = path.read_text(encoding='utf-8')
    corrected = original
    for old, new in REPLACEMENTS.items():
        if old in corrected:
            if corrected.count(old) != 1:
                raise RuntimeError('OneWire inesperado: revisar parche antes de compilar.')
            corrected = corrected.replace(old, new)
        elif new not in corrected:
            raise RuntimeError('OneWire no coincide con version/parche fijados.')
    if corrected != original:
        path.write_text(corrected, encoding='utf-8', newline='\n')
    return corrected != original


if 'Import' in globals():
    Import('env')
    dependency = Path(env.subst('$PROJECT_LIBDEPS_DIR')) / env.subst('$PIOENV') / 'OneWire' / 'OneWire.cpp'
    patch_onewire(dependency)
