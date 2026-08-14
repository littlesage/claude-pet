' 세션 질문 보드 서버를 콘솔창 없이 백그라운드로 기동한다.
' 시작프로그램(Startup)에서 이 파일의 바로가기가 호출된다.
' pythonw = 콘솔 없는 파이썬.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName) & "\"

' PATH의 pythonw를 먼저 쓰고, 없으면 표준 설치 경로를 훑는다.
' (스토어 스텁은 pythonw를 제공하지 않아 여기서 걸러진다)
pyw = "pythonw.exe"
localPrograms = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\"
If fso.FolderExists(localPrograms) Then
  For Each d In fso.GetFolder(localPrograms).SubFolders
    If fso.FileExists(d.Path & "\pythonw.exe") Then pyw = d.Path & "\pythonw.exe"
  Next
End If

sh.CurrentDirectory = base
' 0 = 창 숨김, False = 종료 대기 안 함
sh.Run """" & pyw & """ """ & base & "question_board.py""", 0, False
