# Maliyet analizi: GCP ve Azure

Tarih: 2026-11-10. Fiyatlar USD liste fiyatıdır, vergi hariçtir. Sanal makine fiyatları resmi fiyat listesini yansıtan üçüncü taraf sitelerden alındı (resmi Azure fiyat API'sine bu ortamdan erişilemedi). **Deploy öncesinde resmi hesaplayıcıyla doğrulayın**: [GCP Pricing Calculator](https://cloud.google.com/products/calculator), [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/).

## 1. Ücretsiz krediler (doğrulandı, garanti değil)

| | GCP | Azure |
|---|---|---|
| Kredi | 300 USD | 200 USD |
| Süre | 90 gün | 30 gün |
| Uygunluk | Daha önce GCP, Maps veya Firebase'de ödeme yapan müşteri olmamak; daha önce deneme almamış olmak; geçerli kart (bazı ülkelerde banka doğrulaması) | Uygun müşteri başına bir hesap; telefon, ön ödemeli olmayan kart, Microsoft veya GitHub hesabı |
| Deneme sırasında kısıtlar | GPU eklenemez, Windows VM yok, Marketplace yok, **kota artışı istenemez** | Kota artışı için kullandıkça öde hesabına geçmek gerekir |
| Bitince | Otomatik ücretli hesaba geçmez. Kredi veya süre bitince kaynaklar durdurulur, 30 gün içinde yükseltilmezse silinir | 30 gün veya kredi bitince devam etmek için kullandıkça öde hesabına yükseltmek gerekir |

Kaynaklar: [GCP free trial](https://docs.cloud.google.com/free/docs/free-cloud-features), [Azure free account terms](https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0044p/).

**Sonuç:** Prototip için GCP'nin 300 USD / 90 günü, Azure'un 200 USD / 30 gününden çok daha uygun. Kredi hakkı hesaba ve ülkeye bağlıdır; konsolda "Free trial" bakiyesini görmeden kredi var saymayın. GCP denemesinde GPU kullanılamadığı için Steam/Proton GPU worker'ı (Phase 5) ücretli hesap gerektirecek.

## 2. Sanal makine fiyatları (saatlik, on-demand / spot)

GCP, europe-west3 (Frankfurt):

| Makine | vCPU / RAM | On-demand | Spot |
|---|---|---|---|
| e2-standard-4 | 4 / 16 GB | 0.173 | 0.104 |
| e2-standard-8 | 8 / 32 GB | 0.345 | 0.207 |
| n2d-standard-8 | 8 / 32 GB | 0.435 | 0.245 |
| c2d-standard-8 | 8 / 32 GB | 0.468 | 0.134 |
| c4d-standard-8 | 8 / 31 GB | 0.437 | 0.261 |

europe-west1 (Belçika) e2-standard-8: 0.295 on-demand (yaklaşık %15 daha ucuz, Türkiye'den biraz daha uzak). Spot fiyatları sık değişir.

Azure (Linux, kullandıkça öde):

| Makine | vCPU / RAM | West Europe | Germany West Central | Spot (West Europe) |
|---|---|---|---|---|
| Standard_D8as_v5 | 8 / 32 GB | 0.416 | 0.416 | 0.085 |
| Standard_F8s_v2 | 8 / 16 GB | 0.388 | 0.388 | (alınamadı) |
| Standard_D4as_v5 | 4 / 16 GB | ~0.208 (tahmin: D8as_v5'in yarısı) | | |

Kaynaklar: [devzero.io e2-standard-8](https://www.devzero.io/instances/gcp/e2-standard-8), [devzero.io europe-west3](https://www.devzero.io/instances/gcp/regions/europe-west3), [holori e2-standard-8 europe-west3](https://calculator.holori.com/gcp/vm/e2-standard-8/europe-west3?os=Linux), [devzero.io D8as_v5](https://www.devzero.io/instances/azure/Standard_D8as_v5), [azurespeed F8s_v2](https://www.azurespeed.com/AzureVmPricing/Standard_F8s_v2).

## 3. Gözden kaçan kalemler

| Kalem | GCP | Not |
|---|---|---|
| Disk | pd-balanced 0.12 USD/GB-ay (europe-west3), pd-standard 0.048 | **VM kapalıyken de ücretlenir.** 30 GB balanced ≈ 3.60 USD/ay. Kaynak: [gcloud-compute.com](https://gcloud-compute.com/diskpricing.html) |
| Dış IP | Kullanımdaki IPv4 ≈ 0.005 USD/saat | Rezerve (statik) IP boşta da ücretlenir. Terraform bu yüzden geçici (ephemeral) IP kullanıyor; IP her başlatmada değişir. (Fiyat güncel listeden doğrulanmalı.) |
| **İnternet çıkışı (egress)** | Standard Tier: ilk 200 GiB/ay ücretsiz, sonra 0.085 USD/GiB. Premium Tier: ~0.12 USD/GiB | **Oyun yayınının en büyük gizli maliyeti.** 3 Mbps = saatte ~1.26 GiB/oyuncu. Terraform varsayılanı Standard Tier. Kaynak: [Network Service Tiers pricing](https://cloud.google.com/network-tiers/pricing), [CloudBolt](https://www.cloudbolt.io/gcp-cost-optimization/gcp-egress-pricing/) |
| Loglama / izleme | Cloud Logging projede ayda 50 GiB'a kadar ücretsiz, GCE metrikleri ücretsiz | Ops Agent log hacmi küçük. |
| Azure | İlk 100 GB/ay çıkış ücretsiz, sonra ~0.087 USD/GB (Avrupa, doğrulanmalı); Standard SKU statik IP ~3.6 USD/ay, VM kapalıyken de | Azure'da boşta maliyet IP yüzünden daha yüksek. |

## 4. Senaryolar (GCP, europe-west3)

`scripts/cost_estimate.py` ile hesaplandı (3 Mbps/oyuncu, 30 GB pd-balanced, Standard Tier):

| Senaryo | Aylık |
|---|---|
| Geliştirme: e2-standard-4, 120 saat/ay (günde ~4 saat), 1 oyuncu | **≈ 25 USD** |
| e2-standard-4, 120 saat, 2 oyuncu | ≈ 34 USD (egress 302 GiB, 200'ü ücretsiz) |
| e2-standard-4 **spot**, 120 saat, 2 oyuncu | ≈ 25 USD |
| e2-standard-4, 2 oyuncu, **Premium Tier** | ≈ 61 USD (egress tek başına 36 USD) |
| e2-standard-8, 7/24 açık, 2 oyuncu 120 saat oynuyor | ≈ 268 USD |
| VM tamamen kapalı (sadece diskler) | ≈ 3.60 USD |

Azure eşdeğeri (D4as_v5 tahmini 0.208 USD/saat × 120 saat ≈ 25 USD + disk ≈ 2.4 USD + statik IP ≈ 3.6 USD + 2 oyuncuda ~200 GB ücretli egress ≈ 17 USD) ≈ 48 USD/ay. 200 USD kredi 30 günde bittiği için uzun prototip dönemi için uygun değil.

## 5. Öneri

1. **GCP, europe-west3, e2-standard-4, on-demand, Standard Network Tier, 20 GB boot + 10 GB data disk.** Phase 0 ölçümleri iki NES sınıfı oturumun 4 vCPU'ya sığdığını gösteriyor (oturum başına ≈0.72 vCPU). PS1 ve 8 vCPU ihtiyacı Phase 1 ölçümünden sonra kararlaştırılacak; `machine_type` değişkeniyle tek satırda büyütülür.
2. İlk denemeler için `spot = true` ~%40 daha ucuz; ama GCP spot VM'i her an durdurabilir. Oyun ortasında kopma kabul edilebilirse kullanın.
3. 300 USD kredi bu kullanımla 90 günü rahatça karşılar. Kredi bitmeden önce bütçe alarmı gelir.

## 6. Maliyet güvenliği (Terraform + VM içinde uygulandı)

| Önlem | Ne yapar | Harcamayı durdurur mu? |
|---|---|---|
| Bütçe alarmı (`google_billing_budget`, %50/%90/%100 + tahmini %100) | E-posta gönderir | **Hayır.** Bütçe alarmları harcamayı otomatik durdurmaz, sadece bildirir. |
| `max_run_duration` (varsayılan 4 saat) | VM bu kadar çalıştıktan sonra GCP onu durdurur (STOP) | Evet, VM için |
| Gece durdurma programı (varsayılan 02:00 İstanbul) | Instance schedule ile VM'i durdurur | Evet, VM için |
| Boşta kapatma (`rc-idle-shutdown`, 30 dk) | Oyun oturumu yoksa ve SSH ile bağlı kimse yoksa VM'i kapatır | Evet, VM için |
| Geçici IP | Kapalıyken IP ücreti yok | Evet |
| `scripts/destroy.sh` | Her şeyi siler, sonra projede kalan diskleri, IP'leri, snapshot'ları listeler | Evet |

VM durdurulduğunda diskler (≈3.60 USD/ay) ücretlenmeye devam eder. Sıfır maliyet için `destroy.sh` veya projeyi silmek gerekir.
