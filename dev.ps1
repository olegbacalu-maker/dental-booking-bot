# dev.ps1 - odna tochka vhoda dlya rutiny: test / mutate / up / check.
#
# Vsya logika v scripts\dev.py, i eto namerenno. V PowerShell 5.1 stderr
# nativnoi komandy (git!) stanovitsya oshibkoi, net operatora &&, a $_ vnutri
# -Command "..." s'edaetsya vneshnei obolochkoi - tri grabli iz CLAUDE.md.
# Iz Pythona ni odna iz nih ne strelyaet.
& "$PSScriptRoot\.venv-desktop\Scripts\python.exe" "$PSScriptRoot\scripts\dev.py" @args
exit $LASTEXITCODE
