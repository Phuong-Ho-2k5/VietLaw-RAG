"""Reviewed M2 v1 authoring inputs. Materialize only into a NEW release directory.

Gold answers are deliberately limited to the approved M1 units. The tuples
below are authored cases, not model-generated answers at runtime.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.dataset import DEFAULT_CORPUS, validate_dataset


# (split, family, topic, [(article, clause)], category, question, expected answer)
CASES = [
    ('dev', 'article-13', 'contract', [('13', '1')], 'direct',
     'Theo phạm vi đã kiểm tại 12/02/2026, hợp đồng lao động là gì?',
     'Là thỏa thuận giữa người lao động và người sử dụng lao động về công việc có trả công, tiền lương, điều kiện làm việc và quyền, nghĩa vụ của hai bên.'),
    ('dev', 'article-13', 'contract', [('13', '1')], 'scenario',
     'Thỏa thuận tên là cộng tác viên, nhưng có việc trả công, tiền lương và công ty quản lý, điều hành, giám sát. Theo Điều 13, đây có phải hợp đồng lao động không?',
     'Có. Với các nội dung đã nêu, tên gọi cộng tác viên không làm thay đổi việc thỏa thuận được coi là hợp đồng lao động.'),
    ('dev', 'article-13', 'contract', [('13', '1')], 'direct',
     'Chỉ nhìn tên gọi của thỏa thuận có đủ để loại trừ hợp đồng lao động theo khoản 1 Điều 13 không?',
     'Không. Cần xem nội dung công việc có trả công, tiền lương và việc một bên quản lý, điều hành, giám sát.'),
    ('dev', 'article-13', 'contract', [('13', '2')], 'direct',
     'Người sử dụng lao động phải giao kết hợp đồng vào thời điểm nào so với việc nhận người lao động vào làm?',
     'Phải giao kết hợp đồng trước khi nhận người lao động vào làm việc.'),
    ('dev', 'article-13', 'contract', [('13', '2')], 'scenario',
     'Công ty định nhận nhân viên vào làm chính thức rồi mới giao kết hợp đồng sau một tuần. Việc này có phù hợp khoản 2 Điều 13 không?',
     'Không phù hợp với yêu cầu giao kết hợp đồng trước khi nhận người lao động vào làm việc.'),
    ('dev', 'article-13', 'contract', [('13', '1')], 'scenario',
     'Hai bên đổi tên hợp đồng thành thỏa thuận dịch vụ nhưng giữ nội dung việc làm trả công, tiền lương và sự quản lý, điều hành, giám sát. Tên mới có loại trừ quan hệ hợp đồng lao động không?',
     'Không. Thỏa thuận với đầy đủ các nội dung đã nêu vẫn được coi là hợp đồng lao động.'),
    ('dev', 'article-13', 'contract', [('13', '1'), ('13', '2')], 'multi_unit',
     'Thỏa thuận việc làm trả lương chịu sự quản lý, điều hành, giám sát được gọi là hợp tác. Nó được coi là hợp đồng lao động không và phải giao kết trước hay sau khi nhận vào làm?',
     'Được coi là hợp đồng lao động dù có tên khác; người sử dụng lao động phải giao kết trước khi nhận người lao động vào làm.'),
    ('dev', 'article-13', 'contract', [('13', '1'), ('13', '2')], 'multi_unit',
     'Hãy nêu nội dung cơ bản của hợp đồng lao động và nghĩa vụ giao kết trước khi nhận vào làm theo hai khoản đã duyệt của Điều 13.',
     'Hợp đồng thỏa thuận công việc có trả công, lương, điều kiện làm việc, quyền và nghĩa vụ hai bên. Người sử dụng lao động phải giao kết trước khi nhận người lao động vào làm.'),
    ('dev', 'article-13', 'contract', [('13', '1')], 'direct',
     'Điều kiện lao động và quyền, nghĩa vụ của hai bên có thuộc nội dung thỏa thuận hợp đồng lao động theo khoản 1 Điều 13 không?',
     'Có. Các nội dung này nằm trong thỏa thuận, cùng với việc làm có trả công và tiền lương.'),
    ('dev', 'article-13', 'contract', [('13', '1')], 'scenario',
     'Một người nhận tiền lương để làm việc dưới sự quản lý, điều hành, giám sát của công ty theo giấy mang tên khoán việc. Có thể coi giấy này là hợp đồng lao động theo khoản 1 Điều 13 không?',
     'Có, theo các nội dung được mô tả. Tên khoán việc không loại trừ việc thỏa thuận được coi là hợp đồng lao động.'),
    ('dev', 'article-24', 'probation', [('24', '1')], 'direct',
     'Hai bên có thể ghi nội dung thử việc ngay trong hợp đồng lao động hay phải lập hợp đồng thử việc riêng?',
     'Có thể thỏa thuận nội dung thử việc trong hợp đồng lao động hoặc giao kết hợp đồng thử việc riêng.'),
    ('dev', 'article-24', 'probation', [('24', '1')], 'scenario',
     'Công ty và người lao động muốn thỏa thuận thử việc bằng hợp đồng thử việc riêng. Khoản 1 Điều 24 có cho phép cách này không?',
     'Có. Giao kết hợp đồng thử việc là một trong hai cách thỏa thuận được khoản 1 Điều 24 nêu.'),
    ('dev', 'article-24', 'probation', [('24', '1')], 'scenario',
     'Nhân viên đề nghị đưa phần thử việc vào hợp đồng lao động thay vì ký giấy riêng. Quy định đã duyệt có cho phép không?',
     'Có thể thỏa thuận đưa nội dung thử việc vào hợp đồng lao động.'),
    ('dev', 'article-24', 'probation', [('24', '1')], 'direct',
     'Ai là các bên thỏa thuận về thử việc theo khoản 1 Điều 24?',
     'Người sử dụng lao động và người lao động là hai bên thỏa thuận.'),
    ('dev', 'article-24', 'probation', [('24', '1')], 'direct',
     'Khoản 1 Điều 24 nêu những cách nào để thỏa thuận nội dung thử việc?',
     'Ghi nội dung thử việc trong hợp đồng lao động hoặc giao kết hợp đồng thử việc.'),
    ('dev', 'article-24', 'probation', [('24', '1')], 'scenario',
     'Bộ phận nhân sự khẳng định mọi thỏa thuận thử việc đều bắt buộc có hợp đồng thử việc riêng. Nhận định này có đúng với khoản 1 Điều 24 không?',
     'Không. Hai bên còn có thể thỏa thuận nội dung thử việc trong hợp đồng lao động.'),
    ('dev', 'article-34', 'termination', [('34', '2')], 'direct',
     'Hoàn thành công việc theo hợp đồng có phải là một trường hợp chấm dứt hợp đồng lao động không?',
     'Có. Đây là trường hợp được khoản 2 Điều 34 liệt kê.'),
    ('dev', 'article-34', 'termination', [('34', '3')], 'direct',
     'Hai bên thỏa thuận chấm dứt hợp đồng lao động có thuộc một trường hợp chấm dứt được luật liệt kê không?',
     'Có, theo khoản 3 Điều 34.'),
    ('dev', 'article-34', 'termination', [('34', '2')], 'scenario',
     'Công việc trong hợp đồng của tôi đã hoàn thành. Trong hai khoản Điều 34 được corpus duyệt, căn cứ nào tương ứng?',
     'Khoản 2 Điều 34 là căn cứ tương ứng với việc hoàn thành công việc theo hợp đồng.'),
    ('dev', 'article-34', 'termination', [('34', '3')], 'scenario',
     'Người lao động và doanh nghiệp cùng đồng ý chấm dứt hợp đồng. Tình huống này thuộc khoản nào của Điều 34 đã duyệt?',
     'Thuộc khoản 3 Điều 34 về hai bên thỏa thuận chấm dứt hợp đồng.'),
    ('dev', 'article-34', 'termination', [('34', '2'), ('34', '3')], 'multi_unit',
     'Theo khoản 2 và khoản 3 Điều 34, hoàn thành công việc và hai bên thỏa thuận chấm dứt có đều là trường hợp chấm dứt hợp đồng không?',
     'Có. Hoàn thành công việc thuộc khoản 2, còn hai bên thỏa thuận chấm dứt thuộc khoản 3.'),
    ('dev', 'article-34', 'termination', [('34', '2'), ('34', '3')], 'multi_unit',
     'Hãy phân biệt căn cứ chấm dứt ở khoản 2 và khoản 3 Điều 34 trong corpus đã duyệt.',
     'Khoản 2 nói về hoàn thành công việc theo hợp đồng; khoản 3 nói về thỏa thuận của hai bên chấm dứt hợp đồng.'),
    ('dev', 'article-34', 'termination', [('34', '3')], 'scenario',
     'Công việc chưa hoàn thành nhưng hai bên đã thỏa thuận chấm dứt hợp đồng. Có căn cứ nào trong hai khoản Điều 34 đã duyệt phù hợp với tình huống không?',
     'Có: khoản 3 Điều 34 về thỏa thuận chấm dứt của hai bên. Không cần dùng căn cứ hoàn thành công việc ở khoản 2 cho tình huống này.'),
    ('dev', 'article-34', 'termination', [('34', '2')], 'direct',
     'Khoản 2 Điều 34 được duyệt trong corpus mô tả trường hợp chấm dứt nào?',
     'Trường hợp công việc theo hợp đồng lao động đã hoàn thành.'),
    ('test', 'article-26', 'probation', [('26', None)], 'direct',
     'Mức lương thử việc tối thiểu bằng bao nhiêu phần trăm lương của công việc đó tại ngày 12/02/2026?',
     'Ít nhất 85% mức lương của công việc đó; hai bên thỏa thuận mức cụ thể.'),
    ('test', 'article-26', 'probation', [('26', None)], 'scenario',
     'Lương công việc là 10 triệu đồng/tháng. Chỉ xét Điều 26, lương thử việc ít nhất là bao nhiêu?',
     'Ít nhất 8,5 triệu đồng/tháng, bằng 85% của 10 triệu đồng.'),
    ('test', 'article-26', 'probation', [('26', None)], 'scenario',
     'Hai bên đồng ý trả lương thử việc bằng 80% mức lương công việc. Thỏa thuận đó có đạt mức tối thiểu tại Điều 26 không?',
     'Không, 80% thấp hơn mức tối thiểu 85% được Điều 26 quy định.'),
    ('test', 'article-26', 'probation', [('26', None)], 'scenario',
     'Lương công việc 8 triệu đồng/tháng, thử việc được trả 7 triệu. Tỷ lệ này có đạt sàn Điều 26 không?',
     'Có xét riêng sàn Điều 26: 7 triệu bằng 87,5%, cao hơn mức tối thiểu 85%; sàn tương ứng là 6,8 triệu.'),
    ('test', 'article-26', 'probation', [('26', None)], 'direct',
     'Điều 26 có bắt buộc lương thử việc phải đúng bằng 85% lương công việc không?',
     'Không. 85% là mức tối thiểu; hai bên có thể thỏa thuận mức cao hơn.'),
    ('test', 'article-26', 'probation', [('26', None)], 'direct',
     'Ai thỏa thuận tiền lương trong thời gian thử việc và bị ràng buộc bởi mức sàn nào?',
     'Người lao động và người sử dụng lao động thỏa thuận, nhưng mức trả không được thấp hơn 85% lương của công việc đó.'),
    ('test', 'article-26', 'probation', [('26', None)], 'scenario',
     'Công ty trả 100% lương công việc trong thời gian thử việc. Xét riêng mức sàn Điều 26, có phù hợp không?',
     'Có xét riêng mức sàn: 100% cao hơn mức tối thiểu 85%.'),
    ('test', 'article-26', 'probation', [('26', None)], 'scenario',
     'Mức lương công việc 12 triệu đồng/tháng và lương thử việc 10 triệu. Chỉ xét tỷ lệ Điều 26, có đủ không?',
     'Không. Sàn là 10,2 triệu đồng, nên 10 triệu thấp hơn mức 85%.'),
    ('test', 'article-90', 'wages', [('90', '1')], 'direct',
     'Theo khoản 1 Điều 90, tiền lương gồm những thành phần nào?',
     'Gồm lương theo công việc hoặc chức danh, phụ cấp lương và các khoản bổ sung khác.'),
    ('test', 'article-90', 'wages', [('90', '1')], 'direct',
     'Phụ cấp lương có nằm trong tiền lương theo định nghĩa ở khoản 1 Điều 90 không?',
     'Có. Phụ cấp lương là một thành phần, cùng lương theo công việc hoặc chức danh và các khoản bổ sung khác.'),
    ('test', 'article-90', 'wages', [('90', '1')], 'scenario',
     'Hợp đồng ghi lương chức danh, phụ cấp lương và khoản bổ sung khác. Các thành phần này có thuộc tiền lương theo Điều 90 không?',
     'Có, ba thành phần được mô tả đều nằm trong định nghĩa tại khoản 1 Điều 90.'),
    ('test', 'article-90', 'wages', [('90', '2')], 'direct',
     'Mức lương theo công việc hoặc chức danh có được thấp hơn mức lương tối thiểu không?',
     'Không được thấp hơn mức lương tối thiểu theo khoản 2 Điều 90.'),
    ('test', 'article-90', 'wages', [('90', '2')], 'scenario',
     'Doanh nghiệp đề xuất lương chức danh thấp hơn mức lương tối thiểu áp dụng. Chỉ xét khoản 2 Điều 90, có được không?',
     'Không. Khoản 2 Điều 90 yêu cầu mức lương theo công việc hoặc chức danh không thấp hơn mức lương tối thiểu.'),
    ('test', 'article-90', 'wages', [('90', '1'), ('90', '2')], 'multi_unit',
     'Hãy nêu các thành phần tiền lương và giới hạn dưới đối với lương công việc hoặc chức danh trong hai khoản Điều 90 đã duyệt.',
     'Tiền lương gồm lương công việc hoặc chức danh, phụ cấp và khoản bổ sung khác. Lương theo công việc hoặc chức danh không được thấp hơn mức tối thiểu.'),
    ('test', 'article-90', 'wages', [('90', '1')], 'direct',
     'Trong định nghĩa khoản 1 Điều 90, tiền lương được ai trả cho ai và để làm gì?',
     'Người sử dụng lao động trả cho người lao động theo thỏa thuận để thực hiện công việc.'),
    ('test', 'article-90', 'wages', [('90', '1'), ('90', '2')], 'multi_unit',
     'Tôi cần dẫn chứng cho cả việc phụ cấp thuộc tiền lương và việc lương chức danh không thấp hơn mức tối thiểu. Cần hai khoản nào trong corpus?',
     'Khoản 1 Điều 90 xác định các thành phần gồm phụ cấp; khoản 2 Điều 90 quy định giới hạn dưới của lương công việc hoặc chức danh.'),
    ('test', 'article-105', 'hours_rest', [('105', '1')], 'direct',
     'Khoản 1 Điều 105 quy định giới hạn thời giờ làm việc bình thường trong một ngày và một tuần là bao nhiêu?',
     'Không quá 8 giờ/ngày và không quá 48 giờ/tuần.'),
    ('test', 'article-105', 'hours_rest', [('105', '2')], 'direct',
     'Nếu quy định thời giờ làm việc theo tuần, giới hạn giờ làm bình thường mỗi ngày và mỗi tuần là bao nhiêu?',
     'Không quá 10 giờ/ngày và 48 giờ/tuần; người sử dụng lao động phải thông báo chế độ thời giờ cho người lao động.'),
    ('test', 'article-105', 'hours_rest', [('105', '2')], 'scenario',
     'Công ty quy định thời giờ làm việc theo tuần. Có phải thông báo cho người lao động biết không?',
     'Có. Khoản 2 Điều 105 yêu cầu thông báo cho người lao động biết khi quy định thời giờ theo ngày hoặc tuần.'),
    ('test', 'article-105', 'hours_rest', [('105', '2')], 'direct',
     'Tuần làm việc 40 giờ được khoản 2 Điều 105 mô tả là bắt buộc hay được Nhà nước khuyến khích?',
     'Được Nhà nước khuyến khích; không diễn giải thành yêu cầu bắt buộc mọi doanh nghiệp theo khoản này.'),
    ('test', 'article-105', 'hours_rest', [('105', '1'), ('105', '2')], 'multi_unit',
     'So sánh giới hạn giờ bình thường trong khoản 1 Điều 105 với trường hợp bố trí theo tuần ở khoản 2.',
     'Khoản 1: tối đa 8 giờ/ngày và 48 giờ/tuần. Theo tuần tại khoản 2: tối đa 10 giờ/ngày và 48 giờ/tuần, kèm nghĩa vụ thông báo.'),
    ('test', 'article-105', 'hours_rest', [('105', '2')], 'scenario',
     'Công ty xếp 10 giờ mỗi ngày trong 5 ngày, đều tính là giờ bình thường theo tuần. Lịch 50 giờ có đạt giới hạn tuần trong khoản 2 Điều 105 không?',
     'Không. Tổng 50 giờ vượt trần 48 giờ bình thường trong một tuần dù từng ngày không quá 10 giờ.'),
    ('test', 'article-105', 'hours_rest', [('105', '2')], 'scenario',
     'Đã thông báo chế độ theo tuần, công ty xếp 9 giờ mỗi ngày trong 5 ngày. Chỉ xét các trần giờ bình thường tại khoản 2 Điều 105, có vượt không?',
     'Không vượt các trần nêu tại khoản 2: 9 giờ/ngày dưới 10 giờ và 45 giờ/tuần dưới 48 giờ. Kết luận chỉ giới hạn ở các trần này.'),
    ('test', 'article-105', 'hours_rest', [('105', '2')], 'scenario',
     'Theo chế độ tuần, một ngày xếp 11 giờ bình thường nhưng tổng tuần chỉ 44 giờ. Có vượt giới hạn ngày của khoản 2 Điều 105 không?',
     'Có. 11 giờ bình thường vượt trần 10 giờ/ngày dù tổng tuần dưới 48 giờ.'),
]

# Negative gold is empty: scope evidence explains why this snapshot cannot answer.
# (split, family, topic, category, date, question, evidence/review reason)
NEGATIVE_CASES = [
    ('dev', 'missing-contract-form', 'contract', 'insufficient_evidence', '2026-02-12',
     'Hợp đồng lao động bắt buộc bằng văn bản trong mọi trường hợp không?',
     'Snapshot không chứa Điều 14 về hình thức và ngoại lệ hợp đồng; Điều 13 không đủ để kết luận.'),
    ('dev', 'missing-contract-form', 'contract', 'insufficient_evidence', '2026-02-12',
     'Hợp đồng lao động điện tử có giá trị như hợp đồng giấy không?',
     'Điều quy định hình thức hợp đồng điện tử chưa được duyệt vào snapshot.'),
    ('dev', 'missing-probation-duration', 'probation', 'insufficient_evidence', '2026-02-12',
     'Kỹ sư có trình độ đại học được thử việc tối đa bao nhiêu ngày?',
     'Snapshot chỉ có khoản 1 Điều 24 và Điều 26 về thử việc; không có Điều 25 về thời gian.'),
    ('dev', 'missing-probation-duration', 'probation', 'insufficient_evidence', '2026-02-12',
     'Một người có được thử việc hai lần cho cùng công việc không?',
     'Chưa có Điều 25 trong snapshot để trả lời quy tắc số lần thử việc.'),
    ('dev', 'missing-termination-notice', 'termination', 'insufficient_evidence', '2026-02-12',
     'Tôi đơn phương nghỉ việc ở hợp đồng không xác định thời hạn phải báo trước bao nhiêu ngày?',
     'Snapshot chỉ duyệt khoản 2 và 3 Điều 34; không có căn cứ về đơn phương chấm dứt và thời hạn báo trước.'),
    ('dev', 'missing-termination-notice', 'termination', 'insufficient_evidence', '2026-02-12',
     'Bỏ việc ngay không báo trước sẽ phải bồi thường bao nhiêu?',
     'Không có điều khoản về nghĩa vụ khi đơn phương chấm dứt trái pháp luật trong snapshot.'),
    ('test', 'missing-minimum-wage-rate', 'wages', 'insufficient_evidence', '2026-02-12',
     'Mức lương tối thiểu vùng I tính bằng đồng tại 12/02/2026 là bao nhiêu?',
     'Điều 90 chỉ đưa ra nguyên tắc mức sàn, không có nghị định và bảng mức tiền theo vùng trong snapshot.'),
    ('test', 'missing-minimum-wage-rate', 'wages', 'insufficient_evidence', '2026-02-12',
     'Doanh nghiệp ở Đà Nẵng phải áp dụng chính xác mức lương tối thiểu bao nhiêu đồng tại ngày đã pin?',
     'Snapshot không chứa bảng địa bàn và mức lương tối thiểu; địa chỉ cũng chưa đủ chi tiết để xác định vùng.'),
    ('test', 'missing-overtime-pay', 'wages', 'insufficient_evidence', '2026-02-12',
     'Làm thêm ngày lễ được trả ít nhất bao nhiêu phần trăm lương?',
     'Chưa duyệt điều khoản tính lương làm thêm giờ vào snapshot; Điều 90 không quy định tỷ lệ này.'),
    ('test', 'missing-overtime-pay', 'wages', 'insufficient_evidence', '2026-02-12',
     'Tính tiền lương làm thêm ban đêm ngày Chủ nhật cho tôi với lương giờ 50.000 đồng.',
     'Không có căn cứ về lương làm thêm và ban đêm trong snapshot để tính số tiền.'),
    ('test', 'missing-annual-leave', 'hours_rest', 'insufficient_evidence', '2026-02-12',
     'Người làm đủ một năm trong điều kiện bình thường được bao nhiêu ngày nghỉ phép hưởng lương?',
     'Khoản 1 và 2 Điều 105 chỉ quy định giờ bình thường; snapshot không chứa điều về nghỉ hằng năm.'),
    ('test', 'missing-annual-leave', 'hours_rest', 'insufficient_evidence', '2026-02-12',
     'Làm việc sáu tháng thì số ngày nghỉ hằng năm được tính như thế nào?',
     'Chưa có điều khoản về nghỉ hằng năm và cách tính theo thời gian làm việc trong snapshot.'),
    ('dev', 'outside-family-law', 'outside_scope', 'out_of_scope', '2026-02-12',
     'Khi ly hôn, quyền nuôi con dưới ba tuổi được giải quyết thế nào?',
     'Câu hỏi hôn nhân gia đình nằm ngoài năm chủ đề lao động của snapshot.'),
    ('dev', 'outside-family-law', 'outside_scope', 'out_of_scope', '2026-02-12',
     'Tài sản chung vợ chồng được chia như thế nào khi ly hôn?',
     'Chia tài sản hôn nhân không thuộc phạm vi corpus lao động đã duyệt.'),
    ('test', 'outside-land-law', 'outside_scope', 'out_of_scope', '2026-02-12',
     'Cần những giấy tờ nào để sang tên quyền sử dụng đất?',
     'Thủ tục đất đai nằm ngoài phạm vi corpus lao động.'),
    ('test', 'outside-land-law', 'outside_scope', 'out_of_scope', '2026-02-12',
     'Tranh chấp ranh giới đất giữa hai hộ gia đình được xử lý ra sao?',
     'Tranh chấp đất đai không thuộc năm chủ đề lao động được hỗ trợ.'),
    ('test', 'outside-criminal-law', 'outside_scope', 'out_of_scope', '2026-02-12',
     'Hành vi trộm cắp xe máy bị phạt tù bao nhiêu năm?',
     'Câu hỏi hình sự nằm ngoài phạm vi snapshot lao động.'),
    ('test', 'outside-criminal-law', 'outside_scope', 'out_of_scope', '2026-02-12',
     'Điều kiện được hưởng án treo khi bị kết án là gì?',
     'Điều kiện án treo không thuộc phạm vi corpus lao động.'),
    ('dev', 'temporal-contract-current', 'contract', 'temporal', None,
     'Hiện nay công ty có thể gọi hợp đồng lao động là hợp đồng cộng tác viên để đổi bản chất không?',
     'Câu hỏi dùng hiện nay, không xác định ngày; snapshot chỉ xác minh 12/02/2026. Yêu cầu làm rõ thời điểm, không tự áp dụng ngày đã pin.'),
    ('dev', 'temporal-contract-current', 'contract', 'temporal', '2026-10-08',
     'Ngày 08/10/2026 công ty phải giao kết hợp đồng trước khi nhận người lao động vào làm không?',
     '08/10/2026 chưa được xác minh trong snapshot; cần nguồn/duyệt cho ngày đó hoặc hỏi người dùng về phạm vi 12/02/2026.'),
    ('dev', 'temporal-probation-future', 'probation', 'temporal', '2027-01-01',
     'Từ 01/01/2027 còn được thỏa thuận thử việc trong hợp đồng lao động không?',
     'Snapshot không xác minh hiệu lực tại 01/01/2027; không dự báo pháp luật tương lai.'),
    ('dev', 'temporal-probation-future', 'probation', 'temporal', '2028-01-01',
     'Vào 01/01/2028 có bắt buộc mọi trường hợp thử việc ký hợp đồng riêng không?',
     '01/01/2028 ngoài ngày được xác minh; không thể kết luận từ snapshot hiện có.'),
    ('test', 'temporal-wages-history', 'wages', 'temporal', '2020-01-01',
     'Tại 01/01/2020 tiền lương theo pháp luật gồm những khoản nào?',
     'Snapshot chỉ xác minh 12/02/2026; không có bản được duyệt cho 01/01/2020 để trả lời lịch sử.'),
    ('test', 'temporal-wages-history', 'wages', 'temporal', '2015-01-01',
     'Ngày 01/01/2015 lương chức danh có được thấp hơn mức tối thiểu không?',
     'Snapshot không xác minh pháp luật tại 01/01/2015; không áp dụng hồi tố các chunk ngày 12/02/2026.'),
]


def build_rows(corpus):
    chunks = {(c['article_label'], c['clause_label']): c for c in corpus['chunks']}
    rows = []
    for index, (split, family, topic, refs, category, question, answer) in enumerate(CASES, 1):
        selected = [chunks[ref] for ref in refs]
        rows.append({
            'schema_version': 1, 'question_id': f'M2-Q{index:03}', 'question': question,
            'split': split, 'family_id': family, 'category': category,
            'scope': 'in_scope', 'topic': topic, 'as_of_date': '2026-02-12',
            'expected_behavior': 'answer', 'expected_answer': answer,
            'snapshot_id': corpus['manifest_hash'],
            'gold': [{'document_number': c['document_number'], 'article': c['article_label'],
                      'clause': c['clause_label'], 'point': c['point_label'],
                      'chunk_id': c['chunk_id']} for c in selected],
            'evidence': [{'kind': 'legal_source', 'chunk_id': c['chunk_id'],
                          'url': c['source_evidence']['url'],
                          'pdf_page': c['source_evidence']['pdf_page']} for c in selected],
            'reviewer': 'Codex (assistant; source and gold review)', 'reviewed_at': '2026-10-08',
            'review_note': 'Đối chiếu câu hỏi và đáp án với toàn unit M1 và trang PDF chính thức; giữ điều kiện, không mở rộng kết luận ngoài gold.'
        })
    for index, (split, family, topic, category, as_of, question, reason) in enumerate(NEGATIVE_CASES, len(CASES) + 1):
        rows.append({
            'schema_version': 1, 'question_id': f'M2-Q{index:03}', 'question': question,
            'split': split, 'family_id': family, 'category': category,
            'scope': 'out_of_scope' if category == 'out_of_scope' else 'in_scope',
            'topic': topic, 'as_of_date': as_of, 'expected_behavior': 'abstain',
            'expected_answer': 'Không kết luận nội dung pháp luật từ snapshot này. ' + reason,
            'snapshot_id': corpus['manifest_hash'], 'gold': [],
            'evidence': [{'kind': 'corpus_scope', 'snapshot_id': corpus['manifest_hash'], 'reason': reason}],
            'reviewer': 'Codex (assistant; source and gold review)', 'reviewed_at': '2026-10-08',
            'review_note': reason,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New release directory')
    parser.add_argument('--corpus', type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()
    rows = build_rows(json.loads(args.corpus.read_text(encoding='utf-8')))
    dev, test = [r for r in rows if r['split'] == 'dev'], [r for r in rows if r['split'] == 'test']
    # Seed covers answer/multi-unit/abstention; every seed row stays in dev.
    seed_ids = {1, 2, 4, 7, 11, 12, 17, 21, 49, 51, 61, 67}
    seed = [r for r in dev if int(r['question_id'][4:]) in seed_ids]
    report = validate_dataset(dev, test, seed, json.loads(args.corpus.read_text(encoding='utf-8')))
    args.output.mkdir(parents=True, exist_ok=False)
    for name, records in [('dev', dev), ('test', test), ('seed', seed)]:
        with (args.output / f'{name}.jsonl').open('x', encoding='utf-8', newline='\n') as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    print(json.dumps(report['counts']))


if __name__ == '__main__':
    main()
