param(
  [Parameter(Mandatory = $true)][string]$PrinterName,
  [Parameter(Mandatory = $true)][string]$FilePath
)

# Envia bytes crus (RAW) direto para o spooler da impressora, sem passar pelo
# driver grafico do Windows. Necessario para mandar ZPL para a ELGIN L42PRO.

$src = @"
using System;
using System.IO;
using System.Runtime.InteropServices;

public static class RawPrinterHelper
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DOCINFOW
    {
        [MarshalAs(UnmanagedType.LPWStr)] public string pDocName;
        [MarshalAs(UnmanagedType.LPWStr)] public string pOutputFile;
        [MarshalAs(UnmanagedType.LPWStr)] public string pDataType;
    }

    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool OpenPrinter(string pPrinterName, out IntPtr phPrinter, IntPtr pDefault);

    [DllImport("winspool.drv", SetLastError = true)]
    public static extern bool ClosePrinter(IntPtr hPrinter);

    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool StartDocPrinter(IntPtr hPrinter, int level, ref DOCINFOW pDocInfo);

    [DllImport("winspool.drv", SetLastError = true)]
    public static extern bool EndDocPrinter(IntPtr hPrinter);

    [DllImport("winspool.drv", SetLastError = true)]
    public static extern bool StartPagePrinter(IntPtr hPrinter);

    [DllImport("winspool.drv", SetLastError = true)]
    public static extern bool EndPagePrinter(IntPtr hPrinter);

    [DllImport("winspool.drv", SetLastError = true)]
    public static extern bool WritePrinter(IntPtr hPrinter, byte[] pBytes, int dwCount, out int dwWritten);

    public static void SendBytes(string printerName, byte[] bytes)
    {
        IntPtr hPrinter;
        if (!OpenPrinter(printerName, out hPrinter, IntPtr.Zero))
            throw new Exception("OpenPrinter falhou (erro " + Marshal.GetLastWin32Error() + "). Confira o nome da impressora.");

        try
        {
            var di = new DOCINFOW { pDocName = "Etiqueta iPad", pOutputFile = null, pDataType = "RAW" };
            if (!StartDocPrinter(hPrinter, 1, ref di))
                throw new Exception("StartDocPrinter falhou (erro " + Marshal.GetLastWin32Error() + ").");
            try
            {
                if (!StartPagePrinter(hPrinter))
                    throw new Exception("StartPagePrinter falhou (erro " + Marshal.GetLastWin32Error() + ").");
                int written;
                if (!WritePrinter(hPrinter, bytes, bytes.Length, out written))
                    throw new Exception("WritePrinter falhou (erro " + Marshal.GetLastWin32Error() + ").");
                EndPagePrinter(hPrinter);
            }
            finally { EndDocPrinter(hPrinter); }
        }
        finally { ClosePrinter(hPrinter); }
    }
}
"@

$ErrorActionPreference = "Stop"
try {
  Add-Type -TypeDefinition $src -Language CSharp
  $bytes = [System.IO.File]::ReadAllBytes($FilePath)
  [RawPrinterHelper]::SendBytes($PrinterName, $bytes)
  Write-Output "OK: $($bytes.Length) bytes enviados para '$PrinterName'"
  exit 0
} catch {
  Write-Output ("ERRO: " + $_.Exception.Message)
  exit 1
}
