$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root 'VietLaw_RAG_Project_Plan_Revised.xlsx'

# id | milestone | title | planned hours | dependency | deliverable | acceptance | reference
$rows = @(
'M0-T01|M0|Khóa ZIP và kiểm kê 8.532 JSON|5|Không|Inventory path, id, hash, size, schema|Valid + quarantine = 8.532; ZIP bất biến|docs/DATASET_REBUILD.md',
'M0-T02|M0|Báo cáo chất lượng dữ liệu thô|7|M0-T01|Báo cáo thiếu, trùng, độ dài và lĩnh vực|Số liệu tái tạo được từ cùng ZIP hash|docs/DATASET_REBUILD.md',
'M1-T01|M1|Lọc ứng viên 5 chủ đề|6|M0-T02|Manifest ứng viên và lý do chọn/loại|Không chỉ dựa vào URL hoặc từ khóa|docs/DATASET_REBUILD.md',
'M1-T02|M1|Đối chiếu nguồn và hiệu lực|8|M1-T01|Metadata, nguồn chính thức, log reviewer|Version chưa rõ hiệu lực bị cách ly|docs/DATASET_REBUILD.md',
'M1-T03|M1|Chuẩn hóa text và tách điều/khoản|7|M1-T02|Canonical text, offsets và legal units|Kiểm tối thiểu 10 điều/khoản mỗi loại văn bản|docs/DATASET_REBUILD.md',
'M1-T04|M1|Khử trùng và duyệt corpus v1|5|M1-T03|Manifest approved và quarantine|Mỗi chunk active có provenance và reviewer|docs/DATASET_REBUILD.md',
'M2-T01|M2|Xây seed câu hỏi có căn cứ|6|M1-T04|Câu hỏi và gold theo văn bản/điều|Gồm câu trong phạm vi, ngoài phạm vi, thiếu chứng cứ|docs/DATASET_REBUILD.md',
'M2-T02|M2|Mở rộng dev/test tối thiểu 60 câu|8|M2-T01|Hai tập đánh giá có reviewer và evidence URL|Tách theo văn bản hoặc nhóm câu tương đồng|docs/DATASET_REBUILD.md',
'M2-T03|M2|Validator và đóng băng test|4|M2-T02|Schema validator và split manifest|Không dùng test để chọn tham số|docs/DATASET_REBUILD.md',
'M3-T01|M3|FastAPI và PostgreSQL/pgvector|5|M1-T04|Runtime, config, health và DB migration|Checkout mới khởi động API và DB|docs/RAG_ARCHITECTURE.md',
'M3-T02|M3|Schema và ingestion jobs|7|M3-T01|Models và worker nhập dữ liệu|Retry không tạo bản sao; lỗi có trạng thái|docs/RAG_ARCHITECTURE.md',
'M3-T03|M3|Embedding worker và chỉ mục|7|M3-T02|Vector, model/dimension/hash, full-text index|Chỉ chunk approved được index|docs/RAG_ARCHITECTURE.md',
'M3-T04|M3|Review và snapshot bất biến|5|M3-T03|Admin review và activate nguyên tử|Một snapshot mặc định active; history giữ bản cũ|docs/RAG_ARCHITECTURE.md',
'M4-T01|M4|Keyword, vector, hybrid retrieval|7|M3-T04|Ba chế độ trên cùng snapshot, fusion, trace|Không trả chunk chưa duyệt hoặc sai version|docs/RAG_ARCHITECTURE.md',
'M4-T02|M4|Query rewrite và context|7|M4-T01|Câu hỏi độc lập và context có budget|Không tự thêm điều kiện; giữ quy tắc/ngoại lệ|docs/RAG_ARCHITECTURE.md',
'M4-T03|M4|Generation và kiểm citation|7|M4-T02|Claims có source IDs, quote từ DB|Citation thuộc snapshot và quote đúng text|docs/RAG_ARCHITECTURE.md',
'M4-T04|M4|Chat API và lịch sử|5|M4-T03|API chat, nguồn, conversation, trace|Nguồn cũ mở được; lỗi provider không thành câu trả lời|docs/RAG_ARCHITECTURE.md',
'M5-T01|M5|React shell và đăng nhập|5|M4-T04|Frontend kết nối API và quản lý phiên|Login, refresh, logout qua backend|docs/RAG_ARCHITECTURE.md',
'M5-T02|M5|Chat, lịch sử và panel nguồn|8|M5-T01|UI hỏi đáp và mở đúng đoạn trích|Hiển thị đủ trạng thái kết quả|docs/RAG_ARCHITECTURE.md',
'M5-T03|M5|Admin nhập, duyệt, activate|5|M5-T01; M3-T04|UI quản trị corpus và job|Hoàn tất snapshot mới trong browser|docs/RAG_ARCHITECTURE.md',
'M6-T01|M6|Đo ba retrieval baseline|6|M4-T04; M2-T03|Recall@5, MRR@10 trên cùng test/snapshot|Báo cáo số thực và mẫu số|docs/PROJECT_PLAN.md',
'M6-T02|M6|Đánh giá citation và grounding|6|M6-T01|Precision, abstain, latency, rà soát claims|Không ghi mục tiêu là kết quả đạt|docs/RAG_ARCHITECTURE.md',
'M6-T03|M6|Sửa lỗi và regression toàn luồng|5|M6-T02; M5-T03|Regression cho lỗi nghiêm trọng|E2E câu có và thiếu căn cứ qua UI|docs/PROJECT_PLAN.md',
'M7-T01|M7|Docker Compose và CI|7|M6-T03|Frontend, API, worker, DB và migration|Checkout sạch chạy được|docs/PROJECT_PLAN.md',
'M7-T02|M7|README, demo và báo cáo cuối|5|M7-T01|Tài liệu cài đặt, manifest, evaluation|Người khác tái lập được demo và số đo|docs/PROJECT_PLAN.md'
)
$milestones = @(
@('M0','Kiểm kê ZIP','ZIP gốc','Inventory tái tạo được'),
@('M1','Dựng lại dataset','M0','Corpus 5 chủ đề có duyệt'),
@('M2','Dữ liệu đánh giá','M1','Ít nhất 60 câu có dev/test'),
@('M3','Nền tảng và ingestion','M1','Snapshot active bất biến'),
@('M4','RAG API','M2; M3','Chat API có citation kiểm được'),
@('M5','Giao diện React','M4','Chat, nguồn, admin dùng được'),
@('M6','Đánh giá và sửa lỗi','M4; M5','Báo cáo số đo thực'),
@('M7','Đóng gói','M6','Checkout sạch chạy được')
)

function Put($sheet, $r, $c, $value) {
    $cell = $sheet.Cells.Item($r,$c)
    try {
        if ($value -is [string]) { $cell.Value2 = [string]$value }
        else { $cell.Value2 = [double]$value }
    }
    catch { throw ('Cell {0}!R{1}C{2}, value={3}, type={4}: {5}' -f $sheet.Name,$r,$c,$value,$value.GetType().Name,$_.Exception.Message) }
}
function Header($range) {
    $range.Interior.Color = 0x5E3A19
    $range.Font.Color = 0xFFFFFF
    $range.Font.Bold = $true
    $range.WrapText = $true
    $range.VerticalAlignment = -4108
}
function Title($sheet, $endCol, $title, $subtitle) {
    $sheet.Range(('A2:{0}2' -f $endCol)).Merge()
    Put $sheet 2 1 $title
    $sheet.Range(('A2:{0}2' -f $endCol)).Font.Size = 18
    $sheet.Range(('A2:{0}2' -f $endCol)).Font.Bold = $true
    $sheet.Rows.Item(2).RowHeight = 34
    $sheet.Range(('A3:{0}3' -f $endCol)).Merge()
    Put $sheet 3 1 $subtitle
    $sheet.Rows.Item(3).RowHeight = 27
}
$excel = $null
$book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Add()
    while ($book.Worksheets.Count -lt 3) { [void]$book.Worksheets.Add() }
    while ($book.Worksheets.Count -gt 3) { $book.Worksheets.Item($book.Worksheets.Count).Delete() }
    $overview = $book.Worksheets.Item(1); $overview.Name = 'Tong quan'
    $task = $book.Worksheets.Item(2); $task.Name = 'Task'
    $detail = $book.Worksheets.Item(3); $detail.Name = 'Chi tiet'

    Title $overview 'H' 'VietLaw RAG — Kế hoạch điều chỉnh' 'Dựa trên selected-contexts.zip; chỉ corpus đã duyệt được dùng cho RAG.'
    Put $overview 5 1 'Số task'; Put $overview 5 2 25
    Put $overview 5 3 'Giờ kế hoạch'; Put $overview 5 4 153
    Put $overview 5 5 'Đã hoàn thành'; $overview.Cells.Item(5,6).Formula = '=COUNTIF(Task!F7:F31,"Hoàn thành")'
    Put $overview 5 7 'Tiến độ'; $overview.Cells.Item(5,8).Formula = '=SUMPRODUCT(Task!D7:D31,Task!G7:G31)/SUM(Task!D7:D31)'
    $overview.Cells.Item(5,8).NumberFormat='0%'
    Put $overview 7 1 'Giờ/tuần'; Put $overview 7 2 15
    Put $overview 7 3 'Tuần ước lượng'; $overview.Cells.Item(7,4).Formula='=ROUNDUP(D5/B7,0)'
    Put $overview 7 5 'Nguồn thô'; Put $overview 7 6 '8.532 JSON'
    Put $overview 7 7 'Trạng thái'; Put $overview 7 8 'Chưa triển khai'
    $heads=@('Mốc','Nội dung','Giờ','Phụ thuộc','Đầu ra nghiệm thu','Task','Hoàn thành','Tiến độ')
    for ($i=0; $i -lt $heads.Count; $i++) { Put $overview 10 ($i+1) $heads[$i] }
    Header $overview.Range('A10:H10')
    for ($i=0; $i -lt 8; $i++) {
        $r=11+$i; $m=$milestones[$i]
        Put $overview $r 1 $m[0]; Put $overview $r 2 $m[1]
        $overview.Cells.Item($r,3).Formula = ('=SUMIF(Task!B7:B31,A{0},Task!D7:D31)' -f $r)
        Put $overview $r 4 $m[2]; Put $overview $r 5 $m[3]
        $overview.Cells.Item($r,6).Formula = ('=COUNTIF(Task!B7:B31,A{0})' -f $r)
        $overview.Cells.Item($r,7).Formula = ('=COUNTIFS(Task!B7:B31,A{0},Task!F7:F31,"Hoàn thành")' -f $r)
        $overview.Cells.Item($r,8).Formula = ('=IFERROR(SUMPRODUCT((Task!B7:B31=A{0})*Task!D7:D31*Task!G7:G31)/C{0},0)' -f $r)
        $overview.Cells.Item($r,8).NumberFormat='0%'
        $overview.Rows.Item($r).RowHeight=36
    }
    $overview.Range('A20:H20').Merge(); Put $overview 20 1 '153 giờ ≈ 11 tuần ở 15 giờ/tuần; chuyển mốc theo nghiệm thu.'
    $overview.Range('A22:H22').Merge(); Put $overview 22 1 'ZIP: 1.125 thiếu name; 20 passage rỗng; 459 URL ở nhánh Lao-dong-Tien-luong. Đây chưa phải corpus hợp lệ.'
    $overview.Range('A24:H24').Merge(); Put $overview 24 1 'Chi tiết: docs/PROJECT_PLAN.md · docs/DATASET_REBUILD.md · docs/RAG_ARCHITECTURE.md'
    $overview.Columns.Item('A').ColumnWidth=12; $overview.Columns.Item('B').ColumnWidth=27
    $overview.Columns.Item('C').ColumnWidth=18; $overview.Columns.Item('D').ColumnWidth=18
    $overview.Columns.Item('E').ColumnWidth=50; $overview.Columns.Item('F').ColumnWidth=15
    $overview.Columns.Item('G').ColumnWidth=17; $overview.Columns.Item('H').ColumnWidth=18
    $overview.Range('A10:H24').WrapText=$true

    Title $task 'M' 'VietLaw RAG — Theo dõi 25 task' 'Ô vàng: cập nhật thực tế. Chỉ chọn Hoàn thành sau nghiệm thu.'
    $task.Range('A5:M5').Merge(); Put $task 5 1 'M0–M2 khóa chất lượng dữ liệu trước RAG; giờ kế hoạch có thể đổi sau khi đối chiếu nguồn.'
    $taskHeads=@('Task ID','Mốc','Công việc','Giờ kế hoạch','Phụ thuộc','Trạng thái','Tiến độ','Giờ thực tế','Ngày bắt đầu','Ngày kết thúc','Đầu ra','Tiêu chí nghiệm thu','Tài liệu')
    for ($i=0; $i -lt 13; $i++) { Put $task 6 ($i+1) $taskHeads[$i] }
    Header $task.Range('A6:M6')
    for ($i=0; $i -lt 25; $i++) {
        $r=7+$i; $t=$rows[$i].Split('|')
        for ($j=0; $j -lt 5; $j++) { if ($j -eq 3) { Put $task $r ($j+1) ([int]$t[$j]) } else { Put $task $r ($j+1) $t[$j] } }
        Put $task $r 6 'Chưa bắt đầu'; Put $task $r 7 0
        Put $task $r 11 $t[5]; Put $task $r 12 $t[6]; Put $task $r 13 $t[7]
        $task.Cells.Item($r,7).NumberFormat='0%'
        $task.Rows.Item($r).RowHeight=58
    }
    $task.Range('F7:J31').Interior.Color=0xD7F2FF
    $task.Range('I7:J31').NumberFormat='dd/mm/yyyy'
    $task.Range('A6:M31').AutoFilter() | Out-Null
    $task.Range('F7:F31').Validation.Add(3,1,1,'Chưa bắt đầu,Đang thực hiện,Chờ duyệt,Hoàn thành,Chặn')
    $widths=@(12,8,43,13,20,17,11,13,16,16,52,58,29)
    for ($i=0; $i -lt 13; $i++) { $task.Columns.Item($i+1).ColumnWidth=$widths[$i] }
    $task.Range('A6:M31').WrapText=$true
    $task.Range('A6:M31').VerticalAlignment=-4108
    $task.Activate(); $excel.ActiveWindow.SplitRow=6; $excel.ActiveWindow.FreezePanes=$true

    Title $detail 'E' 'VietLaw RAG — Tiêu chí thực hiện' 'Mỗi task có đầu ra và kiểm tra nghiệm thu cụ thể.'
    $detailHeads=@('Task ID','Mốc','Đầu ra cần đạt','Kiểm tra nghiệm thu','Tài liệu tham chiếu')
    for ($i=0; $i -lt 5; $i++) { Put $detail 5 ($i+1) $detailHeads[$i] }
    Header $detail.Range('A5:E5')
    for ($i=0; $i -lt 25; $i++) {
        $r=6+$i; $t=$rows[$i].Split('|')
        Put $detail $r 1 $t[0]; Put $detail $r 2 $t[1]
        Put $detail $r 3 $t[5]; Put $detail $r 4 $t[6]; Put $detail $r 5 $t[7]
        $detail.Rows.Item($r).RowHeight=56
    }
    $detail.Columns.Item('A').ColumnWidth=12; $detail.Columns.Item('B').ColumnWidth=9
    $detail.Columns.Item('C').ColumnWidth=66; $detail.Columns.Item('D').ColumnWidth=75
    $detail.Columns.Item('E').ColumnWidth=32
    $detail.Range('A5:E30').WrapText=$true
    $detail.Range('A5:E30').VerticalAlignment=-4108
    $detail.Range('A5:E30').AutoFilter() | Out-Null
    $detail.Activate(); $excel.ActiveWindow.SplitRow=5; $excel.ActiveWindow.FreezePanes=$true
    $overview.Activate()
    $excel.CalculateFull()
    $book.SaveAs($out,51)
    Write-Output "Saved $out"
}
finally {
    if ($book) { $book.Close($false); [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($book) }
    if ($excel) { $excel.Quit(); [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
