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
- **Dự kiến vào đất liền**: tỉnh ven biển mà đường bão hướng tới và thời điểm, ví dụ „Dự kiến vào khu vực Quảng Bình khoảng 2026-08-13 12:00 (theo JMA)". Đường đi lấy theo thứ tự tin cậy JMA → ECMWF → các mô hình khác, và quỹ đạo quá khứ lẫn dự báo được lưu trong thuộc tính để vẽ lên bản đồ
- Cảnh báo thời tiết chính thức (CAP) cho vị trí đã chọn

**Khác**

- Hỗ trợ mọi địa điểm AccuWeather có (tìm theo tên, gồm 63 tỉnh thành và hầu hết quận/huyện)
- Tự nhận đơn vị của trang và quy đổi về °C, km/h, km, mm — không bị đọc 90°F thành 90°C
- Tùy chọn thời gian cập nhật (5–60 phút, mặc định 15 phút)

## Cài đặt

### Cài đặt qua HACS (khuyến nghị)

#### Phương pháp 1: Nút "Thêm vào HACS" (đơn giản nhất)

[![Thêm vào HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=smarthomeblack&repository=accuweather&category=integration)

1. Nhấp vào nút "Thêm vào HACS" ở trên (hoạt động khi bạn đã đăng nhập vào Home Assistant).
2. Xác nhận thêm kho lưu trữ vào HACS.
3. Tìm và cài đặt "accuweather" từ menu HACS > Tích hợp.
4. Khởi động lại Home Assistant.
5. Thêm tích hợp: Cài đặt > Thiết bị & Dịch vụ > Thêm tích hợp > accuweather.
6. Chọn tỉnh/thành phố và quận/huyện mà bạn muốn hiển thị thông tin thời tiết.
7. Tùy chọn cấu hình thời gian cập nhật (mặc định là 10 phút).


### Cài đặt thủ công

1. Tải xuống [bản phát hành mới nhất](https://github.com/smarthomeblack/accuweather/releases) hoặc sao chép nội dung repository.
2. Sao chép thư mục `custom_components/accuweather` vào thư mục `custom_components` trong cài đặt Home Assistant của bạn.
3. Khởi động lại Home Assistant.
4. Thêm tích hợp: Cài đặt > Thiết bị & Dịch vụ > Thêm tích hợp > accuweather.
5. Chọn tỉnh/thành phố và quận/huyện mà bạn muốn hiển thị thông tin thời tiết.
6. Tùy chọn cấu hình thời gian cập nhật (mặc định là 10 phút).

## Cấu hình

Bạn có thể thay đổi cấu hình của tích hợp bất cứ lúc nào:

1. Đi tới Cài đặt > Thiết bị & Dịch vụ
2. Tìm tích hợp Weather Vn và nhấn vào Tùy chọn
3. Cấu hình:
   - Chọn tỉnh/thành phố
   - Cài đặt thời gian cập nhật (từ 5 đến 60 phút)
   - Chọn quận/huyện

## Sử dụng

Sau khi cài đặt, các entity sau sẽ được tạo ra:

- `weather.accuweather_<địa_điểm>`: thời tiết hiện tại, dự báo ngày và dự báo giờ
- Cảm biến thời tiết: RealFeel, chỉ số nhiệt, độ ẩm, khí áp, gió, gió giật, hướng gió, tầm nhìn, mật độ mây, trần mây, điểm sương, UV, giờ mặt trời mọc/lặn, pha mặt trăng
- Cảm biến không khí: `Air Quality Index`, `Air Quality Category`, và từng chất PM2.5, PM10, O3, NO2, SO2, CO
- Cảm biến MinuteCast: tóm tắt mưa 2 giờ tới
- 22 cảm biến sức khỏe & hoạt động
- Cảm biến bão: `Storm Count`, `Nearby Storm Count`, `Nearest Storm Distance`, `Nearest Storm Movement`, `Nearest Storm Landfall`, `Storm 1`, `Storm 2`, `Storm 3`, `Weather Alerts`

### Ví dụ tự động hoá: báo khi bão hướng vào đất liền

```yaml
automation:
  - alias: Cảnh báo bão vào đất liền
    triggers:
      - trigger: state
        entity_id: sensor.accuweather_ha_noi_nearest_storm_landfall
    conditions:
      - condition: template
        value_template: "{{ 'Dự kiến vào khu vực' in trigger.to_state.state }}"
    actions:
      - action: notify.mobile_app
        data:
          title: >-
            {{ state_attr('sensor.accuweather_ha_noi_storm_1', 'name') }} —
            {{ state_attr('sensor.accuweather_ha_noi_storm_1', 'classification') }}
          message: >-
            {{ states('sensor.accuweather_ha_noi_nearest_storm_movement') }}.
            {{ trigger.to_state.state }}.
            Cách {{ states('sensor.accuweather_ha_noi_nearest_storm_distance') }} km.
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

- Dữ liệu cập nhật theo thời gian đã cấu hình (mặc định 15 phút). Mỗi lượt cập nhật tải 8 trang AccuWeather, nên đặt dưới 10 phút sẽ tăng nguy cơ bị chặn.
- **Nếu tất cả entity thành „unavailable"**: xem log Home Assistant. Khi thấy thông báo „AccuWeather từ chối yêu cầu (HTTP 403)" thì mạng của bạn đang bị hệ thống chống bot của AccuWeather chặn — không phải lỗi cấu hình. Thử đổi mạng/DNS hoặc tăng thời gian cập nhật. Tích hợp chỉ thử lại 2 lần khi gặp 403 để không kéo dài mỗi lượt cập nhật.
- Dữ liệu bão lấy từ endpoint công khai của Windy, gộp sẵn JMA, NOAA NHC, UKMO, BoM, IMD cùng các mô hình tự dò trên ECMWF/GFS/ICON. Endpoint này không có tài liệu chính thức nên có thể thay đổi; khi đó các sensor bão sẽ trống chứ không làm hỏng phần thời tiết.
- **Dự kiến vào đất liền là ước lượng**, tính từ điểm dự báo gần bờ nhất (ngưỡng 80 km) so với toạ độ tham chiếu của các tỉnh ven biển. Đây không phải bản tin chính thức — khi có bão thật, hãy theo dõi thêm bản tin của Trung tâm Dự báo KTTV Quốc gia.
- Độ chính xác của dữ liệu thời tiết phụ thuộc AccuWeather; một số khu vực không có đủ dữ liệu chi tiết (ví dụ nơi không có chỉ số phấn hoa hoặc MinuteCast).

## Phát triển trong tương lai

- Thêm hỗ trợ cho các khu vực du lịch đặc biệt
- Cải thiện giao diện và hiển thị dữ liệu
- Tùy chọn hiển thị đơn vị đo (metric/imperial)

## Đóng góp

Mọi đóng góp đều được hoan nghênh. Vui lòng tạo issues hoặc pull requests trên [GitHub](https://github.com/smarthomeblack/accuweather).