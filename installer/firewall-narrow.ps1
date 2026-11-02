# DentPilot: vhodyashchie razresheniya brandmauera - tolko iz svoej podseti.
# Zovet master (ot administratora) pri ustanovke i obnovlenii; razbor - v
# DentPilot.iss, stroka [Run] s etim fajlom. Tolko ASCII: Windows PowerShell 5.1
# chitaet fajl bez BOM v kodirovke ANSI (derzhit test_installer).
#
# Suzhaet razreshayushchee VHODYASHCHEE pravilo s RemoteAddresses '*' (ili pusto),
# esli ego imya = -Name (bez ucheta registra) ili programma = -Engine / -Shell.
# Zaprety, ishodyashchie, chuzhie programmy i uzhe suzhennye - ne trogaet.
# Kody: 0 - vse, chto nado, suzheno (ili nechego); 2 - chast' ne suzilas';
# 3 - brandmauer ne otvetil. Master kod ne proveryaet: ustanovka ne padaet.
param(
    [string]$Name = '',
    [string]$Engine = '',
    [string]$Shell = '',
    [switch]$DryRun,
    [object[]]$Rules
)
$ErrorActionPreference = 'Stop'

function Norm([string]$p) {
    if (-not $p) { return '' }
    try {
        $x = [Environment]::ExpandEnvironmentVariables($p.Trim().Trim('"'))
        return [IO.Path]::GetFullPath($x).ToLowerInvariant()
    } catch { return '' }
}

$progs = @(@($Engine, $Shell) | ForEach-Object { Norm $_ } | Where-Object { $_ })
if (-not $PSBoundParameters.ContainsKey('Rules')) {
    try { $Rules = @((New-Object -ComObject HNetCfg.FwPolicy2).Rules) }
    catch { Write-Output "fw-narrow: firewall unavailable: $($_.Exception.Message)"; exit 3 }
}

$failed = 0
foreach ($r in $Rules) {
    # NET_FW_RULE_DIR_IN = 1, NET_FW_ACTION_ALLOW = 1
    if ($r.Direction -ne 1 -or $r.Action -ne 1) { continue }
    $ra = ([string]$r.RemoteAddresses).Trim()
    if ($ra -and $ra -ne '*') { continue }
    $byName = $Name -and ([string]$r.Name -eq $Name)
    $app = Norm ([string]$r.ApplicationName)
    if (-not $byName -and -not ($app -and ($progs -contains $app))) { continue }
    $what = "$($r.Name) | $($r.ApplicationName) | proto $($r.Protocol) | profiles $($r.Profiles)"
    if ($DryRun) { Write-Output "would narrow: $what"; continue }
    try {
        # Pravilo okna "Razreshit' dostup" Windows - edge traversal "defer to user",
        # a ego Windows dopuskaet tol'ko bez uslovij, krome programmy i protokola:
        # RemoteAddresses do snyatiya otvergaetsya (opyt 02.11; tak upal netsh 2.8.0).
        if ($r.EdgeTraversalOptions) { $r.EdgeTraversalOptions = 0 }
        $r.RemoteAddresses = 'LocalSubnet'
        Write-Output "narrowed: $what"
    } catch {
        $failed++
        Write-Output "failed: $what : $($_.Exception.Message)"
    }
}
if ($failed) { exit 2 }
exit 0
