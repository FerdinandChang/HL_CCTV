Set WshShell = CreateObject("WScript.Shell")
strDesktop = WshShell.SpecialFolders("Desktop")
Set objShortcut = WshShell.CreateShortcut(strDesktop & "\花蓮營建路污辨識系統.lnk")
objShortcut.TargetPath = WshShell.CurrentDirectory & "\啟動監測系統(無黑窗).vbs"
objShortcut.WorkingDirectory = WshShell.CurrentDirectory
objShortcut.IconLocation = WshShell.CurrentDirectory & "\frontend\favicon.ico, 0"
objShortcut.Description = "啟動花蓮營建路污辨識系統 (HL_CCTV)"
objShortcut.Save
MsgBox "桌面捷徑已成功建立！" & vbCrLf & "可在桌面直接雙擊 [花蓮營建路污辨識系統] 啟動。", vbInformation, "建立成功"
