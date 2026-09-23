# claude-pet

바탕화면 상주 Claude Code 세션 알림 위젯(Python tkinter 투명 오버레이) + 세션 질문 보드.

- 실행: `pet.pyw`(시작프로그램 `ClaudePet.lnk`), 질문 보드 `question_board.py`(`QuestionBoard.lnk`)
- 훅: `~/.claude/settings.json`의 Stop·Notification 훅이 `pet_hook.py`를 호출 → `events.jsonl` → 말풍선. 경로를 바꾸면 settings.json도 함께 고칠 것
- 원격: GitHub `littlesage/claude-pet` — **공개(PUBLIC) 레포**. 개인 경로·토큰·회사 정보를 커밋하지 않는다
- 상세 사용법·구조: `README.md`
