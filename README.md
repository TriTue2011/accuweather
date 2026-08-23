# AccuWeather

Component tích hợp thông tin thời tiết và chất lượng không khí Việt Nam cho Home Assistant, sử dụng nguồn dữ liệu từ AccuWeather.

## Tính năng

**Thời tiết (nguồn AccuWeather)**

- Thời tiết hiện tại: nhiệt độ, RealFeel, chỉ số nhiệt, độ ẩm, điểm sương, khí áp kèm xu hướng, gió và gió giật, tầm nhìn, mật độ mây, trần mây, chỉ số UV
- Mặt trời và mặt trăng: giờ mọc/lặn, độ dài ngày, pha mặt trăng
- Dự báo 15 ngày: nhiệt cao/thấp, xác suất mưa, số giờ mưa, UV tối đa, RealFeel và RealFeel Shade, gió
- Dự báo 72 giờ (3 ngày, mức miễn phí của AccuWeather), mỗi giờ có đầy đủ chi tiết
- Chất lượng không khí: chỉ số AQI, phân loại, 6 chất ô nhiễm (PM2.5, PM10, O3, NO2, SO2, CO) kèm AQI riêng, và dự báo AQI 4 ngày
- MinuteCast: tóm tắt mưa và bảng 240 phút
- 22 chỉ số sức khỏe & hoạt động (hen suyễn, viêm khớp, chạy bộ, câu cá, lái xe, muỗi...)

**Theo dõi bão (nguồn Windy, không cần API key)**

- Danh sách mọi cơn bão đang hoạt động, sắp theo khoảng cách tới vị trí của bạn
- Mỗi cơn bão một sensor riêng (`Storm 1/2/3`), kèm: cấp bão theo thang Việt Nam (áp thấp nhiệt đới → siêu bão), cấp Beaufort, sức gió km/h, áp suất, khoảng cách và bão đang ở phía nào
- **Hướng di chuyển** viết bằng chữ, ví dụ „Di chuyển hướng Tây Bắc, 21 km/h", suy ra từ hai điểm quỹ đạo gần nhất
- **Dự kiến vào đất liền** (trên từng sensor `Storm 1/2/3`): nơi đường bão gặp đất liền đầu tiên — tỉnh ven biển nếu là Việt Nam, tên nước nếu là chỗ khác — kèm thời điểm, ví dụ „Dự kiến vào Quảng Bình khoảng 12:00 13/08 (theo JMA)". Đường đi lấy theo thứ tự tin cậy JMA → ECMWF → các mô hình khác, và quỹ đạo quá khứ lẫn dự báo được lưu trong thuộc tính để vẽ lên bản đồ
- **Sensor `Nearest Storm Landfall` chỉ nói chuyện đổ bộ vào quốc gia bạn chọn** — chọn lúc cài đặt, mặc định là quốc gia của địa điểm bạn thêm, đổi lại được trong Tùy chọn. Có cơn nào cắt vào bờ nước đó thì nó ghi tên cơn bão, nơi sắp vào (tỉnh nếu là Việt Nam), thời điểm, khoảng cách còn lại và khoảng cách từ chỗ bạn: „Bão Kajiki: Dự kiến vào Quảng Trị khoảng 22:00 25/08, còn khoảng 380 km (~18 giờ nữa), cách bạn 210 km, cấp 13 khi đổ bộ (theo JMA)". Không có cơn nào thì chỉ một dòng „Không có bão đổ bộ Việt Nam", kèm thuộc tính `landfall_in_country: false` để dashboard ẩn thẻ đi (`watched_country` cho biết đang theo dõi nước nào). Bão vòng qua Philippines rồi mới sang Việt Nam vẫn tính đúng: điểm cắt bờ của nước đang theo dõi được dò riêng, chứ không lấy chỗ bão gặp đất liền đầu tiên
- Cảnh báo thời tiết chính thức (CAP) cho vị trí đã chọn
- Khi không có bão nào: các sensor báo „Không có bão", `Storm Count` = 0. Khi bão tan hoặc bão mới xuất hiện gần hơn, các slot tự xếp lại theo khoảng cách — `Storm 1` luôn là cơn gần bạn nhất.
- Khi không gọi được Windy: **giữ nguyên số liệu bão lần trước** và đánh dấu thuộc tính `stale: true`, thay vì báo „Không có bão" — đang bão mà sensor tự nhiên nói hết bão là kiểu sai tệ nhất.

**Khác**

- Hỗ trợ mọi địa điểm AccuWeather có: tìm theo tên, gồm 63 tỉnh thành **và quận/huyện, phường/xã**. Thêm bao nhiêu địa điểm cũng được — mỗi địa điểm là một thiết bị riêng và **đều có đủ bộ sensor bão**, tính khoảng cách và hướng theo đúng toạ độ của địa điểm đó.
- Tự nhận đơn vị của trang và quy đổi về °C, km/h, km, mm — không bị đọc 90°F thành 90°C
- Cập nhật mặc định 5 phút, nhưng **không phải lần nào cũng tải hết**: mỗi lượt chỉ tải lại thời tiết hiện tại, MinuteCast và dữ liệu bão; còn dự báo, chất lượng không khí và chỉ số sức khỏe tải lại mỗi 4 lượt. Nhờ vậy số request tới AccuWeather mỗi giờ *ít hơn* so với việc tải hết mỗi 15 phút, mà thông tin đang thay đổi lại về nhanh hơn ba lần.
- Dữ liệu bão được **chia sẻ giữa mọi địa điểm**: thêm vị trí thứ hai hay thứ mười cũng không phát sinh thêm request tới Windy.
- Tự phục hồi khi cookie hết hiệu lực: gặp HTTP 403 thì xoá cookie và bắt tay lại ngay trong lượt đó, không phải chờ khởi động lại Home Assistant.

## Yêu cầu

**Home Assistant 2024.11 trở lên.** Tích hợp khởi tạo coordinator với tham số `config_entry`, tham số này chỉ có từ 2024.11; trên bản cũ hơn tích hợp sẽ báo lỗi khi khởi động.

## Cài đặt

### Cài đặt qua HACS (khuyến nghị)

#### Phương pháp 1: Nút "Thêm vào HACS" (đơn giản nhất)

[![Thêm vào HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TriTue2011&repository=accuweather&category=integration)

1. Nhấp vào nút "Thêm vào HACS" ở trên (hoạt động khi bạn đã đăng nhập vào Home Assistant).
2. Xác nhận thêm kho lưu trữ vào HACS.
3. Tìm và cài đặt "accuweather" từ menu HACS > Tích hợp.
4. Khởi động lại Home Assistant.
5. Thêm tích hợp: Cài đặt > Thiết bị & Dịch vụ > Thêm tích hợp > accuweather.
6. Chọn tỉnh/thành phố và quận/huyện mà bạn muốn hiển thị thông tin thời tiết.
7. Tùy chọn cấu hình thời gian cập nhật (mặc định 5 phút) và **quốc gia theo dõi bão đổ bộ** (mặc định lấy theo quốc gia của địa điểm vừa chọn).


### Cài đặt thủ công

1. Tải xuống [bản phát hành mới nhất](https://github.com/TriTue2011/accuweather/releases) hoặc sao chép nội dung repository.
2. Sao chép thư mục `custom_components/accuweather` vào thư mục `custom_components` trong cài đặt Home Assistant của bạn.
3. Khởi động lại Home Assistant.
4. Thêm tích hợp: Cài đặt > Thiết bị & Dịch vụ > Thêm tích hợp > accuweather.
5. Chọn tỉnh/thành phố và quận/huyện mà bạn muốn hiển thị thông tin thời tiết.
6. Tùy chọn cấu hình thời gian cập nhật (mặc định 5 phút) và **quốc gia theo dõi bão đổ bộ** (mặc định lấy theo quốc gia của địa điểm vừa chọn).

## Cấu hình

Bạn có thể thay đổi cấu hình của tích hợp bất cứ lúc nào:

1. Đi tới Cài đặt > Thiết bị & Dịch vụ
2. Tìm tích hợp AccuWeather và nhấn vào Tùy chọn
3. Cấu hình:
   - Thời gian cập nhật (từ 3 đến 60 phút)
   - Ngôn ngữ sensor (theo Home Assistant, tiếng Việt, hoặc tiếng Anh)
   - Quốc gia theo dõi bão đổ bộ

## Sử dụng

Sau khi cài đặt, các entity sau sẽ được tạo ra:

- `weather.accuweather_<địa_điểm>`: thời tiết hiện tại, dự báo ngày và dự báo giờ
- Cảm biến thời tiết: RealFeel, chỉ số nhiệt, độ ẩm, khí áp, gió, gió giật, hướng gió, tầm nhìn, mật độ mây, trần mây, điểm sương, UV, giờ mặt trời mọc/lặn, pha mặt trăng
- Cảm biến không khí: `Air Quality Index`, `Air Quality Category`, và từng chất PM2.5, PM10, O3, NO2, SO2, CO
- Cảm biến MinuteCast: tóm tắt mưa 2 giờ tới
- 22 cảm biến sức khỏe & hoạt động
- Cảm biến bão: `Storm Count`, `Nearby Storm Count`, `Nearest Storm Distance`, `Nearest Storm Movement`, `Nearest Storm Landfall`, `Storm 1`, `Storm 2`, `Storm 3`, `Weather Alerts`

### Ví dụ tự động hoá: báo khi bão hướng vào bờ

```yaml
automation:
  - alias: Cảnh báo bão đổ bộ
    triggers:
      - trigger: state
        entity_id: sensor.accuweather_ha_noi_nearest_storm_landfall
    conditions:
      - condition: template
        value_template: "{{ state_attr(trigger.entity_id, 'landfall_in_country') }}"
    actions:
      - action: notify.mobile_app
        data:
          title: >-
            {{ state_attr(trigger.entity_id, 'classification') }}
            {{ state_attr(trigger.entity_id, 'name') }} —
            {{ state_attr(trigger.entity_id, 'landfall_province') }}
          message: >-
            {{ trigger.to_state.state }}
```

### Xem bản đồ bão trong Home Assistant

Thêm một thẻ `iframe` vào dashboard (không cần API key):

```yaml
type: iframe
url: https://embed.windy.com/embed2.html?lat=16&lon=112&zoom=5&overlay=hurricanes&product=ecmwf&metricWind=km%2Fh&metricTemp=%C2%B0C
aspect_ratio: 75%
```

Đổi `overlay=hurricanes` thành `radar`, `waves` hoặc `gust` để xem lớp khác.

## Các tỉnh/thành phố hỗ trợ

Tích hợp hỗ trợ tất cả 63 tỉnh thành của Việt Nam, được phân loại theo 8 vùng miền:

- Đông Bắc Bộ: Hà Giang, Cao Bằng, Bắc Kạn, Tuyên Quang, Thái Nguyên,...
- Tây Bắc Bộ: Lào Cai, Điện Biên, Lai Châu, Sơn La, Yên Bái,...
- Đồng bằng Sông Hồng: Hà Nội, Hải Phòng, Hải Dương, Hưng Yên,...
- Bắc Trung Bộ: Thanh Hóa, Nghệ An, Hà Tĩnh, Quảng Bình,...
- Nam Trung Bộ: Đà Nẵng, Quảng Nam, Quảng Ngãi, Bình Định,...
- Tây Nguyên: Kon Tum, Gia Lai, Đắk Lắk, Đắk Nông, Lâm Đồng
- Đông Nam Bộ: TP. Hồ Chí Minh, Bà Rịa - Vũng Tàu, Bình Dương,...
- Đồng bằng Sông Cửu Long: Cần Thơ, Long An, Tiền Giang, Bến Tre,...

## Quận/huyện hỗ trợ

Tích hợp hỗ trợ hầu hết các quận/huyện của 63 tỉnh thành, bao gồm cả các khu vực đặc biệt như biển, vùng núi và các đảo.

## Chú ý

- **Không có cách nào để website tự đẩy thay đổi về Home Assistant.** AccuWeather chỉ là trang web (không có webhook/websocket), Windy cũng chỉ có endpoint HTTP với cache 60 giây — nên buộc phải hỏi lại theo chu kỳ. Cách gần nhất với „thay đổi là thấy" là chu kỳ ngắn nhưng chỉ tải phần hay đổi, và đó là cách tích hợp này đang làm (xem mục Tính năng). Nếu cần cập nhật ngay lập tức, gọi dịch vụ `homeassistant.update_entity` trên entity thời tiết trong tự động hoá của bạn.
- Dữ liệu cập nhật theo thời gian đã cấu hình (mặc định 5 phút, tối thiểu 3 phút). Đặt quá ngắn vẫn tăng nguy cơ bị chặn vì mỗi lượt vẫn có 2 trang, và mỗi 4 lượt có 8 trang.
- **Về lỗi HTTP 403 và VPN.** AccuWeather đứng sau Akamai Bot Manager: hệ thống này đánh giá client theo *dấu vết TLS* chứ không chỉ User-Agent, cộng thêm điểm rủi ro của địa chỉ IP. Hệ quả thực tế là chạy từ IP nhà mạng Việt Nam thì thường không sao, nhưng bật VPN — nhất là VPN đặt ở trung tâm dữ liệu như Hong Kong hay Singapore — là bị chặn ngay dù không đổi gì trong cấu hình.

  Tích hợp xử lý bằng thư viện [`curl_cffi`](https://pypi.org/project/curl_cffi/), nó bắt tay TLS giống Chrome thật nên vượt được. Thư viện đã nằm trong `requirements` của manifest, Home Assistant tự cài lúc khởi động. Đã kiểm chứng trên một IP trung tâm dữ liệu đang bị chặn: cách cũ trả 403, cách này trả về đủ dữ liệu.

  **Không cần thêm địa chỉ hay domain nào vào cấu hình VPN.** Loại AccuWeather khỏi VPN gần như không làm được, vì Akamai dùng hàng nghìn IP anycast thay đổi liên tục.

  Nếu vẫn gặp 403, đọc thông báo trong log — nó phân biệt hai trường hợp: đã dùng dấu vết trình duyệt mà vẫn bị chặn (hãy đổi máy chủ VPN hoặc tắt VPN cho Home Assistant), hoặc `curl_cffi` chưa cài được (tìm lỗi cài đặt trong log lúc khởi động). Tích hợp chỉ thử lại 2 lần khi gặp 403 để không kéo dài mỗi lượt cập nhật.
- Dữ liệu bão lấy từ endpoint công khai của Windy, gộp sẵn JMA, NOAA NHC, UKMO, BoM, IMD cùng các mô hình tự dò trên ECMWF/GFS/ICON. Endpoint này không có tài liệu chính thức nên có thể thay đổi; khi đó các sensor bão sẽ trống chứ không làm hỏng phần thời tiết.
- **Dự kiến vào đất liền là ước lượng**, tính từ điểm dự báo gần bờ nhất (ngưỡng 80 km) so với toạ độ tham chiếu của các tỉnh ven biển Việt Nam và đường bờ biển các nước trong vùng. Đây không phải bản tin chính thức — khi có bão thật, hãy theo dõi thêm bản tin của Trung tâm Dự báo KTTV Quốc gia.
- Độ chính xác của dữ liệu thời tiết phụ thuộc AccuWeather; một số khu vực không có đủ dữ liệu chi tiết (ví dụ nơi không có chỉ số phấn hoa hoặc MinuteCast).

## Phát triển trong tương lai

- Thêm hỗ trợ cho các khu vực du lịch đặc biệt
- Cải thiện giao diện và hiển thị dữ liệu
- Tùy chọn hiển thị đơn vị đo (metric/imperial)

## Đóng góp

Mọi đóng góp đều được hoan nghênh. Vui lòng tạo issues hoặc pull requests trên [GitHub](https://github.com/TriTue2011/accuweather).