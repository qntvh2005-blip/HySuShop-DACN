# HySuShop

Đồ án nghiên cứu và xây dựng hệ thống gợi ý sản phẩm tích hợp trong website kinh doanh phụ kiện điện thoại. Sinh viên Trần Văn Hiếu, MSSV 1250080054. Project sử dụng Python 3.11, Django 5.2 và PostgreSQL 18.

## Bộ bàn giao và GitHub

Repository chứa mã nguồn, migrations, README, danh sách thư viện và minh chứng kiểm thử. Gửi kèm `CSDL_HySuShop.sql` và `Du_lieu_va_mo_hinh.zip` trong bộ hồ sơ để người kiểm tra có đủ CSDL sạch, dataset và mô hình. Các tệp này không được tải tự động khi sao chép repository.

Chỉ đưa `.env.example` lên GitHub. `.env`, môi trường `.venv`, ảnh người dùng tải lên và dữ liệu vận hành trên máy cá nhân được loại khỏi repository. Các log kiểm thử `reports/**/system_tests.log` được giữ để đối chiếu với báo cáo. Bản kiểm tra hồ sơ nội bộ `reports/gvhd-review-20261119/final_review.json` không thuộc mã nguồn bàn giao.

## Cài đặt và chạy

Môi trường tham chiếu là Windows, Python 3.11.9 và PostgreSQL 18.3. Mở terminal PowerShell trong thư mục chứa `manage.py`. Tạo database và tài khoản PostgreSQL riêng bằng pgAdmin trước khi cấu hình.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Điền `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` trong `.env`. Nếu dùng `DATABASE_URL`, giá trị đó được ưu tiên. Tài khoản chạy kiểm thử cần có quyền tạo database kiểm thử. Giữ `.env` trên máy cài đặt, không đưa mật khẩu vào repository.

## Khôi phục CSDL sạch để kiểm tra đồ án

Giải nén mã nguồn và `Du_lieu_va_mo_hinh.zip` vào cùng thư mục, sao cho `manage.py`, `data` và `artifacts` nằm cùng cấp. File chính `CSDL_HySuShop.sql` được gửi riêng trong bộ hồ sơ nộp; đây là bản xuất đầy đủ cấu trúc bảng, khóa, chỉ mục, sequence, migration và dữ liệu ban đầu.

Bản SQL giữ 709 sản phẩm, trong đó 696 đang mở bán, cùng ảnh, danh mục, thương hiệu, thiết bị tương thích và nhóm quyền. Giá và tồn là ảnh chụp tại thời điểm xuất. Bản nộp đã loại tài khoản, hồ sơ cá nhân, đơn hàng, giỏ, đánh giá, hành vi, phiên đăng nhập và nhật ký demo. Thao tác làm sạch thực hiện trên bản sao riêng; dữ liệu nghiên cứu và mô hình không thay đổi. Các hình và phép khảo sát vận hành trong báo cáo ghi lại giai đoạn trước, không phải dữ liệu sẵn có sau khi khôi phục bản sạch.

Ảnh catalog trong bản SQL được lưu bằng URL nguồn; bản sạch không tham chiếu tệp ảnh tải lên từ máy cũ. Máy xem cần Internet để tải các ảnh này. Dataset đã xử lý và bundle mô hình được cung cấp trong gói riêng, không cần tải lại dữ liệu gốc mỗi lần chạy gợi ý. 13 hồ sơ ngừng bán vẫn được giữ để khớp catalog nghiên cứu 709 mã; chúng không được đưa vào danh sách mua hàng.

Tạo một database PostgreSQL trống bằng pgAdmin và cấp quyền sở hữu cho tài khoản ứng dụng. Không chạy SQL vào database đang dùng. Ví dụ bên dưới dùng tên `dacn_demo` và tài khoản `hysu_app`; thay bằng tên đã tạo và cấu hình khớp trong `.env`. Đặt SQL vào thư mục chứa `manage.py` hoặc sửa lại đường dẫn ở lệnh.

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' --host 127.0.0.1 --port 5432 --username hysu_app --password --dbname dacn_demo --set ON_ERROR_STOP=1 --file .\CSDL_HySuShop.sql
```

Bản SQL dùng câu INSERT có tên cột và đã được kiểm tra bằng cách khôi phục vào database mới, đối chiếu số bản ghi và toàn bộ catalog. File không tạo tài khoản quản trị dùng sẵn; cần tạo mới bằng `createsuperuser` sau các lệnh kiểm tra dưới đây. Với phương án không khôi phục SQL, có thể chạy migration và import catalog theo mục sau.

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py setup_roles
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

Mở http://127.0.0.1:8000/. Trang quản trị riêng nằm ở `/quan-ly/`. Sử dụng Python trong `.venv` để nạp đủ thư viện mô hình. Khi muốn dừng server, nhấn Ctrl+C.

## Dữ liệu và mô hình

Tập `data/processed/amazon-medium-v1` gồm 709 sản phẩm, 1.614 người dùng ẩn danh và 9.456 tương tác tích cực, chọn từ Amazon Reviews 2023 do McAuley Lab công bố. Dữ liệu và biểu mẫu cấu hình được cung cấp cùng bộ hồ sơ nộp. Repository bỏ qua các thư mục dữ liệu và mô hình để quản lý dung lượng. Đặt các thư mục đi kèm về đúng vị trí trước khi chạy.

- Nguồn chính thức https://amazon-reviews-2023.github.io/
- Dataset đã xử lý `data/processed/amazon-medium-v1`
- Nguồn, cấu hình, luật lọc và checksum trong `data/provenance` cùng các manifest của tập xử lý
- Mô hình `artifacts/amazon-medium-v1`, con trỏ `artifacts/active.json`
- Kết quả đã khóa `reports/amazon-medium-v1`
- Kiểm chứng bổ sung theo nhận xét GVHD `reports/gvhd-review-20261119`
- Bổ sung phân tích lý do gợi ý, tách người dùng và đo nhiều độ dài lịch sử `reports/gvhd-followup-20261120`

Tài khoản Amazon trong nghiên cứu là mã ẩn danh, tách biệt tài khoản đăng nhập website. Giá và tồn của cửa hàng phục vụ mô phỏng. COD và hoàn tiền được ghi nhận trong hệ thống.

Bộ bàn giao kiểm chứng tái lập mô hình và các bảng đánh giá từ tập đã xử lý `amazon-medium-v1`. Các tệp nguồn lớn và catalog trung gian không kèm theo; `data/provenance` giữ biên nhận tải, địa chỉ nguồn, revision và checksum để đối chiếu. Chưa kiểm chứng lại toàn bộ chuỗi xử lý từ dữ liệu gốc trên một máy khác. Không diễn giải khả năng chạy lại benchmark từ tập đã xử lý thành đã tái lập độc lập toàn bộ quá trình thu thập và chọn mẫu.

Xem các tùy chọn import trước khi dùng với database mới:

```powershell
.\.venv\Scripts\python.exe manage.py import_research_catalog --help
.\.venv\Scripts\python.exe manage.py import_research_catalog data/processed/amazon-medium-v1
.\.venv\Scripts\python.exe -m research.validate data/processed/amazon-medium-v1
```

Lệnh import tạo nội dung catalog nhưng giữ nguyên giá, tồn kho và trạng thái đang có. Với database trống, quản trị viên cần nhập giá, tồn và kiểm tra thiết bị tương thích trước khi mở bán. Bản sao lưu đi kèm đã có dữ liệu cửa hàng phục vụ demo.

## Tái lập và kiểm chứng

Các lệnh sau dùng thư mục đầu ra mới. Mô hình và kết quả đang phục vụ được giữ trong phiên bản `amazon-medium-v1`.

```powershell
.\.venv\Scripts\python.exe -m research.run_model_job data/processed/amazon-medium-v1 --reports reports/reproduction-v1 --artifacts artifacts/reproduction-v1
.\.venv\Scripts\python.exe -m research.evaluation.revision_audit --output reports/revision-reproduction
.\.venv\Scripts\python.exe manage.py test --settings=config.settings.test
```

Đo tải HTTP cục bộ sẽ tạo và xóa database kiểm thử riêng. Chạy riêng với bộ kiểm thử để tránh tranh chấp database test.

```powershell
.\.venv\Scripts\python.exe -m research.evaluation.serving_audit --output reports/http-reproduction.json
.\.venv\Scripts\python.exe -m research.evaluation.behavior_audit --output reports/behavior-reproduction.json
```

Phép khảo sát hành vi đọc dữ liệu vận hành tại thời điểm chạy. Tệp `behavior_weights_replay.json` lưu hồ sơ trọng số và ứng viên của lượt khảo sát để đối chiếu. Chưa có nhãn mua tương lai để khẳng định cấu hình trọng số tối ưu. Phép đo tải ghi thời gian nhận HTML, dùng catalog mẫu trên một máy cục bộ và tối đa 10 yêu cầu đồng thời.

### Kiểm chứng bổ sung ngày 20/11/2026

```powershell
.\.venv\Scripts\python.exe -m research.evaluation.cold_start_audit --output reports/cold-start-reproduction
.\.venv\Scripts\python.exe -m research.evaluation.mixed_serving_audit --output reports/history-http-reproduction.json
```

Chạy từng lệnh riêng, dùng đường dẫn đầu ra chưa tồn tại. Lệnh đầu tách 1.291 người để khớp, 161 để chọn cấu hình, 162 để test; chỉ khớp bằng 5.003 tương tác từ train cũ của nhóm khớp. Mô hình này chỉ tồn tại trong bộ nhớ, không đổi artifact hoặc kết quả benchmark chính. Không lịch sử dự đoán món tích cực đầu tiên; biết một món dự đoán món thứ hai. Hai mục tiêu khác nhau nên không dùng chênh lệch chỉ số để khẳng định tác dụng của một tương tác. Catalog và metadata vẫn hồi cứu; đây chưa phải khảo sát khách thật.

Lệnh thứ hai tạo rồi xóa database kiểm thử riêng; không chạy cùng bộ test hoặc phép đo khác dùng database test. Ba nhóm hồ sơ 0/3/20 món đã xem, mỗi nhóm 10 tài khoản, ba route, mức đồng thời 1/5/10/20 và 40 yêu cầu mỗi ô, tổng 1.440. Catalog đủ 709 món với giá 99.000 đồng và tồn 20 giả lập trong database test. Hồ sơ được đặt lại trước từng pha và sau làm nóng; yêu cầu chi tiết có thể ghi thêm lượt xem trong pha. Chỉ đo HTML qua localhost sau làm nóng, theo từng route, chưa gồm ảnh, trình duyệt, Internet hoặc hành trình điều hướng hỗn hợp. Bản chạy lưu sẵn có 1.440 HTTP 200; không dùng để cam kết số khách thực tế.

Khả năng giải thích được kiểm chứng qua ba trường hợp có nhật ký: đề xuất cùng nhóm, đề xuất khác nhóm và khách chưa đăng nhập. Giao diện khách giữ thẻ sản phẩm thông thường; quản trị đối chiếu thành phần điểm trong nhật ký. Bản CSDL sạch không có nhật ký cũ, nên bộ minh chứng đã loại định danh tài khoản được giữ tại `reports/gvhd-followup-20261120/explanations/cases.json`. Chỉ có mã sản phẩm, hồ sơ trọng số, tập ứng viên và số liệu của lượt gợi ý; không chứa tài khoản, địa chỉ, số điện thoại hoặc phiên đăng nhập.

```powershell
.\.venv\Scripts\python.exe -m research.evaluation.explanation_audit --snapshot reports/gvhd-followup-20261120/explanations/cases.json --artifact artifacts/amazon-medium-v1 --output reports/explanation-reproduction.json
```

Lệnh dùng tệp đầu ra chưa tồn tại, nạp bundle và tập ứng viên đã lưu để kiểm tra lại điểm, chuẩn hóa, thứ hạng và liên hệ nguồn; không khớp mô hình hoặc ghi CSDL. Ba ví dụ khớp phép tính không đồng nghĩa tỷ lệ gợi ý đúng 100%, chứng minh mua kèm hoặc khách hiểu lời giải thích. Kết quả nằm ở `explanations/audit.json`, log mới của 167 kiểm thử ở `explanations/system_tests.log`. Phép đo tải đã lưu được giữ như kết quả tại thời điểm đo; không chạy lại hoặc sửa số đo khi thay phần trình bày thẻ.

## Nghiệp vụ trả hàng

Khách chọn món và số lượng cần trả ở đơn đã giao, nhập lý do và ảnh. Mỗi đơn có một hồ sơ trả hàng. Quản trị viên duyệt rồi nhập số lượng còn bán được khi nhận hàng. Số lượng hỏng được giữ trong chi tiết hồ sơ, chỉ phần còn bán được cộng vào tồn khả dụng. Tiền hoàn theo đơn giá lưu trong đơn và được mô phỏng. Tổng tiền đơn lúc mua giữ nguyên để đối chiếu; doanh thu ròng trừ tiền đã hoàn.

Có thể truy vấn dữ liệu đã khôi phục bằng Query Tool trong pgAdmin. Trang Hệ thống gợi ý cho phép mở thời điểm từng lần gợi ý để xem điểm và các sản phẩm lịch sử có liên hệ. Nhật ký cũ và nhánh dự phòng có thể chưa lưu thành phần điểm.


## Đối chiếu phiên bản dữ liệu và kết quả

Trước khi đối chiếu số liệu, kiểm tra đồng thời tập xử lý, kết quả và bundle mô hình:

- `data/processed/amazon-medium-v1/config.json`, `statistics.json`, `manifest.json`: cấu hình đầu vào, quy mô và dấu kiểm tra của dữ liệu.
- `reports/amazon-medium-v1/locked_config.json`, `development_grid.json`, `test_metrics.json`: cấu hình chọn trên development và kết quả kiểm thử đã khóa.
- `artifacts/amazon-medium-v1`: bundle và manifest phục vụ; `artifacts/active.json` xác định phiên bản website đang dùng.

Đối chiếu checksum trong manifest, không chỉ tên thư mục. Khi chạy lại thực nghiệm, dùng thư mục đầu ra mới và giữ nguyên con trỏ phục vụ nếu chưa chủ động triển khai mô hình mới. Minh chứng thao tác trong báo cáo bổ sung cho bộ kiểm thử tự động; kết quả chỉ xác nhận các điều kiện và môi trường thử đã nêu.

## Trình tự demo và kiểm tra nghiệp vụ

Khôi phục bản CSDL sạch vào database riêng, tạo tài khoản quản trị và khách hàng mới. Bản sạch không có sẵn đơn hàng, đánh giá hoặc lịch sử tương tác của các ảnh trong báo cáo. Chuẩn bị các sản phẩm còn bán, đủ tồn và đã xác minh thiết bị tương thích.

1. Khi chưa đăng nhập, giới thiệu catalog, tìm kiếm, lọc danh mục, thương hiệu, thiết bị và giá. Thử một tổ hợp có kết quả và một tổ hợp không phù hợp để minh họa thông báo không tìm thấy sản phẩm.
2. Mở chi tiết sản phẩm, chuyển ảnh và kiểm tra thông tin tương thích. Cho xem danh sách sản phẩm được quan tâm khi chưa có hồ sơ cá nhân.
3. Đăng nhập tài khoản khách, đặt thiết bị quan tâm, xem và lưu vài sản phẩm cùng nhóm. Quay lại mục Gợi ý dành cho bạn để đối chiếu ngữ cảnh; thêm và bỏ yêu thích, kiểm tra hồ sơ và lịch sử cá nhân.
4. Thêm hàng, thay đổi số lượng, kiểm tra giỏ rồi đặt đơn COD. Đối chiếu giá lưu trong đơn, tổng tiền và tồn kho trước/sau khi đặt. Dùng một đơn riêng cho nhánh hủy; đơn khác đi qua xác nhận, giao hàng và đã giao để kiểm tra đánh giá sau mua và trả hàng.
5. Trong trang quản lý, giới thiệu tổng quan, sản phẩm và ảnh tải lên, danh mục, thương hiệu, thiết bị tương thích, tài khoản và đơn hàng. Dùng dữ liệu thử riêng khi thêm, sửa hoặc ngừng bán sản phẩm. Kiểm tra quyền trước khi thao tác.
6. Với đơn đã giao, khách đánh giá từ sản phẩm trong đơn, gửi yêu cầu trả theo từng món và số lượng, kèm lý do và ảnh. Quản trị duyệt, nhận hàng, ghi phần còn bán được và phần hỏng. Đối chiếu tồn chỉ tăng ở phần còn bán được, tiền hoàn theo đơn giá đã lưu và lịch sử xử lý; thử gửi lặp để kiểm tra chống xử lý hai lần.
7. Mở mục Hệ thống gợi ý, đối chiếu đúng lần đề xuất, nguồn, thành phần điểm và sản phẩm lịch sử liên quan. Bản sạch chưa có nhật ký cũ; dùng kết quả mới phát sinh hoặc bộ minh chứng đã ẩn định danh tại `reports/gvhd-followup-20261120/explanations`.

Kết thúc bằng phạm vi đã thực hiện và các giới hạn: hệ thống có hai vai trò khách hàng/quản trị viên; COD và hoàn tiền là mô phỏng; mỗi đơn có một hồ sơ trả. Các bước cùng điều kiện kiểm thử chi tiết được mô tả trong Chương 3 của báo cáo. Không dùng dữ liệu demo để thay đổi bộ dữ liệu và kết quả nghiên cứu đã khóa.
