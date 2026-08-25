# AccuWeather

Tích hợp thời tiết, chất lượng không khí và theo dõi bão cho Việt Nam trên Home
Assistant. Gộp **ba nguồn** trả lời ba câu hỏi khác nhau, không cái nào thay
được cái nào:

| Nguồn | Trả lời câu hỏi | Cần API key |
|---|---|---|
| **AccuWeather** | Thời tiết chỗ tôi đang ở thế nào | Không |
| **Windy** | Bão đang ở đâu, đi đâu, bao giờ vào bờ | Không |
| **NCHMF** | Cơ quan khí tượng nhà nước vừa phát tin gì | Không |

---

## Tính năng

### Thời tiết — nguồn AccuWeather

- **Hiện tại**: nhiệt độ, RealFeel, chỉ số nhiệt, độ ẩm, điểm sương, khí áp kèm
  xu hướng, gió và gió giật, tầm nhìn, mật độ mây, trần mây, chỉ số UV
- **Mặt trời và mặt trăng**: giờ mọc/lặn, độ dài ngày, pha mặt trăng
- **Dự báo 15 ngày**: nhiệt cao/thấp, xác suất mưa, số giờ mưa, UV tối đa,
  RealFeel và RealFeel Shade, gió
- **Dự báo 72 giờ** (mức miễn phí của AccuWeather), mỗi giờ đầy đủ chi tiết
- **Chất lượng không khí**: chỉ số AQI, phân loại, sáu chất ô nhiễm (PM2.5,
  PM10, O₃, NO₂, SO₂, CO) kèm AQI riêng từng chất, và dự báo AQI bốn ngày
- **MinuteCast**: tóm tắt mưa hai giờ tới và bảng 240 phút
- **22 chỉ số sức khoẻ và hoạt động**: hen suyễn, viêm khớp, chạy bộ, câu cá,
  lái xe, muỗi…
- Tự nhận đơn vị của trang và quy đổi về °C, km/h, km, mm — không đọc nhầm 90 °F
  thành 90 °C

### Theo dõi bão — nguồn Windy

**Từng cơn bão**

- Ba cảm biến `Bão 1/2/3` (`Storm 1/2/3`), luôn xếp theo khoảng cách nên cảm
  biến thứ nhất là cơn gần bạn nhất. Mỗi cơn có cấp bão theo thang Việt Nam
  (áp thấp nhiệt đới → siêu bão), cấp Beaufort, sức gió km/h, áp suất, khoảng
  cách và hướng so với bạn
- **Hướng di chuyển** viết bằng chữ — „Di chuyển hướng Tây Bắc, 21 km/h" — suy
  ra từ hai điểm quỹ đạo gần nhất
- Quỹ đạo quá khứ và dự báo nằm trong thuộc tính, đủ để vẽ lên bản đồ
- Có nhiều hơn ba cơn thì các cơn xa hơn vẫn nằm đủ trong thuộc tính `storms`
  của `Số cơn bão`, chỉ là không có cảm biến riêng

**Dự báo đổ bộ**

Cảm biến `Nearest storm landfall` **chỉ nói chuyện đổ bộ vào quốc gia bạn chọn** (chọn lúc cài đặt,
mặc định là quốc gia của địa điểm bạn thêm, đổi lại được trong Tuỳ chọn). Bão
vòng qua Philippines rồi mới sang Việt Nam vẫn tính đúng: điểm cắt bờ của nước
đang theo dõi được dò riêng, không lấy chỗ bão gặp đất liền đầu tiên.

- **Kể về cơn vào bờ SỚM NHẤT**, không phải cơn đang gần bạn nhất — một cơn ở xa
  hơn nhưng đi nhanh hơn vẫn có thể vào trước
- **Giờ đổ bộ được nội suy.** Quỹ đạo JMA chạy 3 giờ một điểm trong ngày đầu rồi
  giãn ra 21–24 giờ, mỗi bước đưa bão đi 400–650 km — đủ xa để bước qua luôn bờ
  biển. Đoạn quỹ đạo có đầu mút trong vòng 250 km quanh đất liền được chia nhỏ
  15 km một bước trước khi dò, rồi lấy đúng điểm áp sát bờ nhất. Đo trên dữ liệu
  thật: mốc theo ECMWF lùi lại **9,6 giờ** và sát bờ hơn **48 km** so với cách cũ
- **Nói rõ các mô hình đồng thuận tới đâu.** Mọi mô hình có quỹ đạo đều được dò
  điểm cắt bờ, không chỉ mô hình tin cậy nhất. Câu trạng thái ghi thẳng „3/3 mô
  hình cùng hướng, lệch 95 km" hoặc „chỉ 1/3 mô hình cho vào bờ"
- **Chỉ báo khi bão đã đến đủ gần**: đổ bộ trong vòng **72 giờ** HOẶC bão còn
  cách điểm đổ bộ dưới **1000 km**. Một trong hai là đủ — cơn hai ngày nữa vào
  bờ vẫn đáng lo dù ở xa 1500 km, cơn còn 400 km vẫn đáng lo dù đi chậm mất bốn
  ngày. Bão đã đổ bộ rồi luôn được báo
- **Nhiều cơn cùng hướng vào một nước** thì các cơn còn lại nằm ở `landfall_count`
  và `landfall_storms`, xếp theo thứ tự vào bờ

Ví dụ câu trạng thái:

> Bão Kajiki: Dự kiến vào Quảng Trị khoảng 22:00 25/08, còn khoảng 380 km (~18
> giờ nữa), cách bạn 210 km, cấp 13 khi đổ bộ (theo JMA; 3/3 mô hình cùng hướng,
> lệch 41 km)

Không có cơn nào đủ gần thì chỉ một dòng „Không có bão đổ bộ Việt Nam", kèm
`landfall_in_country: false` để dashboard ẩn thẻ đi.

**Khi trời yên hoặc nguồn hỏng**

- Không có bão nào: các cảm biến báo „Không có bão", `Số cơn bão` = 0
- Không gọi được Windy: **giữ nguyên số liệu lần trước** và đánh dấu
  `stale: true`, thay vì báo „Không có bão" — đang bão mà cảm biến tự nhiên nói
  hết bão là kiểu sai tệ nhất

### Bản tin chính thức — nguồn NCHMF

Cảm biến `Bản tin thời tiết nguy hiểm` đọc trang [thời tiết nguy hiểm](https://www.nchmf.gov.vn/kttv/vi-VN/1/thoi-tiet-nguy-hiem-5-15.html)
của Trung tâm Dự báo Khí tượng Thuỷ văn Quốc gia.

- **Trạng thái gồm tiêu đề rồi tới nội dung**, vì thiếu nửa nào cũng dở: tiêu đề
  không nói bão đang ở đâu, còn đoạn tóm tắt thường mở đầu bằng „1. Hiện trạng
  bão…" chẳng cho biết đây là tin loại gì

  > TIN BÃO TRÊN BIỂN ĐÔNG (Cơn bão số 4) — 1. Hiện trạng bão Hồi 13 giờ ngày
  > 25/8, vị trí tâm bão ở vào khoảng 19,4 độ Vĩ Bắc; 108,1 độ Kinh Đông, trên
  > khu vực Nam Vịnh Bắc Bộ. Sức gió mạnh nhất vùng gần tâm bão mạnh cấp 8
  > (62-74km/h), giật cấp 10. Di…

- **Số hiệu bão Việt Nam** ở thuộc tính `storm_number`: Windy gọi bão theo tên
  quốc tế (Kajiki), Việt Nam đánh số theo thứ tự vào Biển Đông (bão số 4), và
  chỉ bản tin NCHMF mang con số đó
- Toàn văn bản tin ở `content`, bản PDF chính thức ở `pdf_url`. Bảng dự báo trong
  bản tin được đánh dấu `[bảng]` chứ không đổ số vào văn xuôi
- NCHMF còn cảnh báo **lũ, rét, nắng nóng, triều cường** — những thứ một nguồn
  bão nhiệt đới không biết
- Mỗi lượt chỉ tải **thân của bản tin mới nhất**; thân bản tin cũ thì không ai
  đọc, mà mười bản tin là mười request lên một trang của cơ quan nhà nước
- Trang tải lại **15 phút một lần** và dùng chung cho mọi địa điểm. Không vào
  được thì giữ danh sách lần trước và đánh dấu `stale: true`
- Nội dung luôn là tiếng Việt vì nguồn chỉ có tiếng Việt; chỉ **tên** cảm biến
  đổi theo ngôn ngữ đã chọn

### Vận hành

- **Nhiều địa điểm**: thêm bao nhiêu cũng được, mỗi địa điểm là một thiết bị
  riêng và đều có đủ bộ cảm biến bão, tính khoảng cách theo đúng toạ độ của nó
- **Không tải hết mỗi lượt**: mỗi lượt chỉ tải lại thời tiết hiện tại, MinuteCast
  và dữ liệu bão; dự báo, chất lượng không khí và chỉ số sức khoẻ tải lại mỗi 4
  lượt. Nhờ vậy số request tới AccuWeather mỗi giờ *ít hơn* so với tải hết mỗi
  15 phút, mà thông tin đang thay đổi lại về nhanh hơn ba lần
- **Dữ liệu bão và bản tin dùng chung giữa mọi địa điểm**: thêm địa điểm thứ hai
  hay thứ mười cũng không phát sinh thêm request tới Windy hay NCHMF
- **Tự phục hồi khi cookie hết hiệu lực**: gặp HTTP 403 thì xoá cookie và bắt tay
  lại ngay trong lượt đó, không phải chờ khởi động lại Home Assistant

---

## Yêu cầu

**Home Assistant 2024.11 trở lên.** Tích hợp khởi tạo coordinator với tham số
`config_entry`, tham số này chỉ có từ 2024.11; trên bản cũ hơn tích hợp sẽ báo
lỗi khi khởi động.

## Cài đặt

### Qua HACS (khuyến nghị)

[![Thêm vào HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TriTue2011&repository=accuweather&category=integration)

1. Nhấn nút trên (hoạt động khi bạn đã đăng nhập Home Assistant), hoặc thêm thủ
   công kho `TriTue2011/accuweather` dạng *Integration* trong HACS
2. Cài đặt „accuweather" từ HACS
3. Khởi động lại Home Assistant
4. **Cài đặt → Thiết bị & Dịch vụ → Thêm tích hợp → accuweather**
5. Chọn tỉnh/thành phố, rồi quận/huyện

### Thủ công

1. Tải [bản phát hành mới nhất](https://github.com/TriTue2011/accuweather/releases)
   hoặc sao chép kho này
2. Chép thư mục `custom_components/accuweather` vào `custom_components` của Home
   Assistant
3. Khởi động lại rồi thêm tích hợp như bước 4–5 ở trên

## Cấu hình

**Cài đặt → Thiết bị & Dịch vụ → AccuWeather → Tuỳ chọn**

| Tuỳ chọn | Mặc định | Ghi chú |
|---|---|---|
| Thời gian cập nhật | 5 phút | Từ 3 tới 60 phút |
| Ngôn ngữ cảm biến | Theo Home Assistant | `auto`, tiếng Việt, hoặc tiếng Anh |
| Quốc gia theo dõi bão đổ bộ | Quốc gia của địa điểm vừa chọn | Quyết định cảm biến `Dự báo đổ bộ bão gần nhất` nói về bờ biển nước nào |

Đặt thời gian cập nhật quá ngắn vẫn tăng nguy cơ bị chặn, vì mỗi lượt vẫn có hai
trang và cứ bốn lượt lại có tám trang.

---

## Entity được tạo

| Nhóm | Entity |
|---|---|
| Thời tiết | `weather.accuweather_<địa_điểm>` — hiện tại, dự báo ngày và dự báo giờ |
| Cảm biến thời tiết | RealFeel, RealFeel Shade, chỉ số nhiệt, độ ẩm, khí áp, gió, gió giật, hướng gió, tầm nhìn, mật độ mây, trần mây, điểm sương, UV, mặt trời mọc/lặn, pha mặt trăng |
| Không khí | `Chỉ số chất lượng không khí` / `Air quality index` · `Mức chất lượng không khí` / `Air quality category` · PM2.5 · PM10 · O₃ · NO₂ · SO₂ · CO |
| MinuteCast | Tóm tắt mưa hai giờ tới |
| Sức khoẻ & hoạt động | 22 cảm biến |
| Bão | `Số cơn bão` / `Storm count` · `Số bão ở gần` / `Nearby storm count` · `Khoảng cách bão gần nhất` / `Nearest storm distance` · `Cấp bão gần nhất` / `Nearest storm force (Beaufort)` · `Hướng di chuyển bão gần nhất` / `Nearest storm movement` · `Dự báo đổ bộ bão gần nhất` / `Nearest storm landfall` · `Bão 1/2/3` / `Storm 1/2/3` |
| Cảnh báo | `Cảnh báo thời tiết` / `Weather alerts` — CAP chính thức cho vị trí đã chọn |
| Bản tin Việt Nam | `Bản tin thời tiết nguy hiểm` / `NCHMF hazard bulletin` |

### Thuộc tính đáng dùng

**`Dự báo đổ bộ bão gần nhất` / `Nearest storm landfall`**

| Thuộc tính | Ý nghĩa |
|---|---|
| `landfall_in_country` | Có cơn nào sắp vào bờ nước đang theo dõi không — dùng để ẩn/hiện thẻ |
| `watched_country` | Đang theo dõi bờ biển nước nào |
| `landfall_province` · `landfall_time_text` · `landfall_beaufort` | Nơi vào, thời điểm, cấp gió khi đổ bộ |
| `distance_to_landfall_km` · `hours_to_landfall` | Bão còn phải đi bao xa, còn bao lâu |
| `landfall_distance_from_home_km` | Chỗ đổ bộ cách bạn bao xa |
| `landfall_models_agreeing` / `landfall_models_total` | Bao nhiêu mô hình cùng cho ra điểm cắt bờ |
| `landfall_spread_km` · `landfall_spread_hours` · `landfall_places` | Các mô hình lệch nhau bao xa, bao lâu, và nêu những khúc bờ nào |
| `landfall_count` · `landfall_storms` | Tổng số cơn sắp vào bờ và danh sách từng cơn |
| `landfall_beyond_horizon` | Ước lượng bị giữ lại vì còn quá xa và quá lâu |
| `storms_in_maritime_zone` | Các cơn đang trong 370 km tính từ bờ nước đó |
| `landfall_horizon_hours` · `landfall_range_km` | Hai ngưỡng đang đặt ở đâu (72 giờ, 1000 km) |

**`Bản tin thời tiết nguy hiểm` / `NCHMF hazard bulletin`**

| Thuộc tính | Ý nghĩa |
|---|---|
| `title` | Tiêu đề bản tin, đầy đủ |
| `summary` | Đoạn mở đầu, cắt theo câu trọn vẹn |
| `content` | Toàn văn bản tin |
| `pdf_url` | Bản PDF chính thức, khi trang có |
| `storm_number` | Số hiệu bão Việt Nam (bão số 4) |
| `category` | `bão`, `lũ`, `biển`, `mưa`, `nắng nóng`, `rét`, `khác` |
| `issued` · `issued_text` · `url` | Giờ phát (ISO, múi giờ Việt Nam) và liên kết gốc |
| `recent_count` | Số bản tin trong 24 giờ qua — phân biệt lúc đang có việc với lúc yên ắng |
| `bulletins` | Cả danh sách trên trang |

> **Lưu ý về cách xem thuộc tính.** Home Assistant các bản gần đây đã bỏ khung
> thuộc tính khỏi hộp thoại bấm-vào-cảm-biến — bấm vào chỉ thấy Lịch sử và Hoạt
> động. Muốn xem thuộc tính thì vào **Công cụ nhà phát triển → Trạng thái**, hoặc
> đọc bằng template như thẻ Markdown bên dưới.

---

## Ví dụ

### Cảnh báo khi bão hướng vào bờ

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
          message: "{{ trigger.to_state.state }}"
```

### Thẻ đọc trọn bản tin NCHMF

```yaml
type: markdown
content: |-
  {% set e = 'sensor.accuweather_ha_noi_nchmf_hazard_bulletin' %}
  ### {{ state_attr(e,'title') }}
  *{{ state_attr(e,'issued_text') }} · {{ state_attr(e,'category') }}*

  {{ state_attr(e,'content') }}

  [Bản tin gốc]({{ state_attr(e,'url') }}){% if state_attr(e,'pdf_url') %} · [PDF]({{ state_attr(e,'pdf_url') }}){% endif %}
```

### Bản đồ bão

Thẻ `iframe`, không cần API key:

```yaml
type: iframe
url: https://embed.windy.com/embed2.html?lat=16&lon=112&zoom=5&overlay=hurricanes&product=ecmwf&metricWind=km%2Fh&metricTemp=%C2%B0C
aspect_ratio: 75%
```

Đổi `overlay=hurricanes` thành `radar`, `waves` hoặc `gust` để xem lớp khác.

---

## Địa điểm hỗ trợ

Mọi địa điểm AccuWeather có: tìm theo tên, gồm đủ 63 tỉnh thành **và quận/huyện,
phường/xã**, kể cả khu vực biển, vùng núi và đảo.

Tám vùng miền: Đông Bắc Bộ · Tây Bắc Bộ · Đồng bằng Sông Hồng · Bắc Trung Bộ ·
Nam Trung Bộ · Tây Nguyên · Đông Nam Bộ · Đồng bằng Sông Cửu Long.

---

## Giới hạn và lưu ý

### Không có cách nào để nguồn tự đẩy thay đổi về

AccuWeather chỉ là trang web (không webhook, không websocket), Windy chỉ có
endpoint HTTP với cache 60 giây, NCHMF là trang HTML — nên buộc phải hỏi lại
theo chu kỳ. Cần cập nhật ngay thì gọi `homeassistant.update_entity` trên entity
thời tiết trong tự động hoá của bạn.

### Lỗi HTTP 403 và VPN

AccuWeather đứng sau Akamai Bot Manager: hệ thống này đánh giá client theo *dấu
vết TLS* chứ không chỉ User-Agent, cộng thêm điểm rủi ro của địa chỉ IP. Hệ quả
thực tế: chạy từ IP nhà mạng Việt Nam thường không sao, nhưng bật VPN — nhất là
VPN đặt ở trung tâm dữ liệu như Hong Kong hay Singapore — là bị chặn ngay dù
không đổi gì trong cấu hình.

Tích hợp xử lý bằng [`curl_cffi`](https://pypi.org/project/curl_cffi/), thư viện
bắt tay TLS giống Chrome thật nên vượt được. Nó đã nằm trong `requirements` của
manifest, Home Assistant tự cài lúc khởi động. Đã kiểm chứng trên một IP trung
tâm dữ liệu đang bị chặn: cách cũ trả 403, cách này trả về đủ dữ liệu.

**Không cần thêm địa chỉ hay domain nào vào cấu hình VPN** — loại AccuWeather ra
gần như không làm được, vì Akamai dùng hàng nghìn IP anycast đổi liên tục.

Vẫn gặp 403 thì đọc thông báo trong log; nó phân biệt hai trường hợp: đã dùng
dấu vết trình duyệt mà vẫn bị chặn (đổi máy chủ VPN hoặc tắt VPN cho Home
Assistant), hoặc `curl_cffi` chưa cài được (tìm lỗi cài đặt trong log lúc khởi
động). Tích hợp chỉ thử lại hai lần khi gặp 403 để không kéo dài mỗi lượt.

### Dự báo đổ bộ là ƯỚC LƯỢNG

Tính từ quỹ đạo dự báo (chia nhỏ 15 km một bước ở đoạn gần bờ, ngưỡng 80 km) so
với toạ độ tham chiếu của các tỉnh ven biển Việt Nam và đường bờ biển các nước
trong vùng.

**Nội suy làm cho *cách đọc* dự báo chính xác hơn, không làm bản thân dự báo
đúng hơn.** Sai số thật nằm ở chỗ các mô hình bất đồng, và đó chính là thứ
`landfall_spread_km` cùng `landfall_models_agreeing` nói ra.

Điểm mốc bờ biển Việt Nam hiện thưa — 28 điểm, mỗi tỉnh một điểm, cách nhau
23–148 km — nên tên tỉnh chỉ nên đọc như „khúc bờ biển quanh đó". Vùng biển
370 km là xấp xỉ theo bề rộng vùng đặc quyền kinh tế (200 hải lý), **không phải
ranh giới EEZ pháp lý**.

**Đây không phải bản tin chính thức.** Khi có bão thật, hãy theo dõi cảm biến
`Bản tin thời tiết nguy hiểm` và bản tin của Trung tâm Dự báo KTTV Quốc gia.

### Nguồn ngoài có thể đổi

- **Windy**: endpoint công khai, gộp sẵn JMA, NOAA NHC, UKMO, BoM, IMD cùng các
  mô hình tự dò trên ECMWF/GFS/ICON. Không có tài liệu chính thức nên có thể
  đổi; khi đó các cảm biến bão trống chứ không làm hỏng phần thời tiết
- **NCHMF**: bóc từ HTML một trang không có API. Trang đổi giao diện thì cảm biến
  bản tin trống; log gỡ lỗi sẽ có dòng nói trang tải được nhưng không bóc ra bản
  tin nào
- **AccuWeather**: độ chính xác phụ thuộc nguồn; vài khu vực không có đủ dữ liệu
  chi tiết (ví dụ không có chỉ số phấn hoa hoặc MinuteCast)

---

## Đóng góp

Mọi đóng góp đều được hoan nghênh — tạo issue hoặc pull request trên
[GitHub](https://github.com/TriTue2011/accuweather).
