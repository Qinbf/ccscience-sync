$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (Get-Command py -ErrorAction SilentlyContinue) {
  py -3 .\ccscience.py install
  py -3 .\ccscience.py status
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  python .\ccscience.py install
  python .\ccscience.py status
} else {
  throw "Python 3.9 or newer is required."
}
