# Sign-File.ps1 - podpisyvaet ODIN fail (exe) sertifikatom podpisi koda (Authenticode).
#
#   .\Sign-File.ps1 -Path dist\DentPilot.exe
#
# Sertifikat - Certum Cloud Code Signing: zakrytyi klyuch zhivet v oblake Certum,
# na PK ego pokazyvaet SimplySign Desktop kak virtualnuyu kartu v hranilishche
# Windows (Cert:\CurrentUser\My). Kakim sertifikatom podpisyvat - otpechatok v
# peremennoi DENTPILOT_SIGN_THUMBPRINT (ne sekret: otpechatok publichnyi).
# !! Pered sborkoi voiti v SimplySign Desktop (kod iz prilozheniya SimplySign na
# telefone), inache klyuch nedostupen i podpis upadet.
#
# Chem podpisyvaem: signtool, esli nayden (Windows SDK; ili put v
# DENTPILOT_SIGNTOOL), inache vstroennyi Set-AuthenticodeSignature.
# Metka vremeni OBYAZATELNA: bez nee podpis umiraet vmeste so srokom
# sertifikata, i uzhe otdannye klinikam faily zadnim chislom stanovyatsya
# "neizvestnyi izdatel".
#
# Posle podpisi - PROVERKA: fail podpisan imenno etim sertifikatom i s metkoi
# vremeni; inache kod vyhoda 1 (Build-Installer ostanavlivaetsya).
#
# -Pfx / -PfxPassword / -AllowUntrusted - TOLKO dlya proverki mehaniki na
# odnorazovom samopodpisannom sertifikate: ego koren Windows ne znaet, i
# status podpisi "ne doveren" v etom sluchae ne oshibka.
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$Thumbprint = $env:DENTPILOT_SIGN_THUMBPRINT,
    [string]$TimestampUrl = $(if ($env:DENTPILOT_SIGN_TIMESTAMP) { $env:DENTPILOT_SIGN_TIMESTAMP } else { "http://time.certum.pl" }),
    [string]$Pfx = "",
    [string]$PfxPassword = "",
    [switch]$AllowUntrusted
)
$ErrorActionPreference = "Stop"
function Fail($msg) { Write-Host "STOP (podpis): $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path -LiteralPath $Path)) { Fail "net faila $Path" }
$file = (Resolve-Path -LiteralPath $Path).Path

# --- sertifikat ---
if ($Pfx) {
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($Pfx, $PfxPassword)
} else {
    if (-not $Thumbprint) { Fail "ne zadan DENTPILOT_SIGN_THUMBPRINT - otpechatok sertifikata podpisi koda" }
    $Thumbprint = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpper()
    $cert = @("Cert:\CurrentUser\My\$Thumbprint", "Cert:\LocalMachine\My\$Thumbprint") |
            Where-Object { Test-Path $_ } | ForEach-Object { Get-Item $_ } | Select-Object -First 1
    if (-not $cert) { Fail "sertifikat $Thumbprint ne nayden v hranilishche Windows - SimplySign Desktop podklyuchen?" }
}
if (-not $cert.HasPrivateKey) { Fail "u sertifikata net zakrytogo klyucha (SimplySign Desktop: voiti zanovo)" }
$eku = @($cert.Extensions | Where-Object { $_ -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension] } |
         ForEach-Object { $_.EnhancedKeyUsages } | ForEach-Object { $_.Value })
if ($eku -notcontains "1.3.6.1.5.5.7.3.3") { Fail "sertifikat ne dlya podpisi koda (v EKU net Code Signing)" }
if ($cert.NotAfter -lt (Get-Date)) { Fail ("srok sertifikata istek " + $cert.NotAfter.ToString("dd.MM.yyyy")) }

# --- podpis ---
$signtool = $env:DENTPILOT_SIGNTOOL
if (-not $signtool) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -EA SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if ($signtool -and -not $Pfx) {
    & $signtool sign /sha1 $cert.Thumbprint /fd sha256 /tr $TimestampUrl /td sha256 $file | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "signtool vernul $LASTEXITCODE" }
} else {
    try {
        Set-AuthenticodeSignature -LiteralPath $file -Certificate $cert -HashAlgorithm SHA256 `
            -TimestampServer $TimestampUrl -IncludeChain NotRoot | Out-Null
    } catch { Fail ("Set-AuthenticodeSignature: " + $_.Exception.Message) }
}

# --- proverka: nashim sertifikatom i s metkoi vremeni ---
$sig = Get-AuthenticodeSignature -LiteralPath $file
if (-not $sig.SignerCertificate -or $sig.SignerCertificate.Thumbprint -ne $cert.Thumbprint) {
    Fail ("fail ne podpisan etim sertifikatom (status: " + $sig.Status + ")")
}
if (-not $sig.TimeStamperCertificate) { Fail "v podpisi net metki vremeni - $TimestampUrl ne otvetil?" }
if ($sig.Status -ne "Valid" -and -not $AllowUntrusted) { Fail ("podpis ne deistvitelna: " + $sig.Status + " " + $sig.StatusMessage) }
Write-Host ("podpisan: " + (Split-Path $file -Leaf) + " | " + $cert.Subject + " | metka vremeni: " + $sig.TimeStamperCertificate.Subject + " | status: " + $sig.Status)
exit 0
