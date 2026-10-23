import {createContext,useContext,useEffect,useState} from 'react';

const english={
  'Mode pengembangan':'Development mode',
  'Menunggu':'Pending','Terkirim':'Completed','Gagal':'Failed','Tidak ada error':'No errors','Transport cloud belum tersedia di engine.':'Cloud transport is unavailable on this engine.',
  'Pengaturan engine':'Engine settings','Bagian pengaturan':'Settings sections','Kamera dan pemulihan':'Cameras and recovery','Penyimpanan dan rekaman':'Storage and recordings','Tujuan penyimpanan tambahan':'Additional storage destination','Backup dan pemulihan':'Backup and recovery','Status engine':'Engine status',
  'Hubungkan engine untuk mengatur. Jalankan aplikasi terintegrasi melalui run-app.ps1.':'Connect the engine to configure these options. Start the integrated app with run-app.ps1.',
  'Periksa koneksi':'Check connection','Memuat pengaturan...':'Loading settings...','Daftar kamera belum tersedia':'Camera list unavailable','Pulihkan otomatis setelah gangguan':'Automatically recover after interruptions','Pemulihan berlaku per kamera. Zona dan kalibrasi diatur di Pemantauan Live.':'Recovery is configured per camera. Configure zones and calibration in Live Monitoring.',
  'Auto-save laporan data':'Automatically save data reports','Auto-save rekaman video':'Automatically save video recordings','Interval simpan data (detik)':'Data save interval (seconds)','Durasi potongan video (detik)':'Video segment duration (seconds)','Batas penyimpanan (MB)':'Storage limit (MB)','Simpan pengaturan rekaman':'Save recording settings','Folder penyimpanan lokal':'Local storage folder','File tersimpan':'Saved files',
  'Jenis tujuan':'Destination type','Lokal aplikasi':'Application folder','Folder server / NAS':'Server / NAS folder','Cloud melalui rclone':'Cloud via rclone','Aktifkan pengiriman tambahan':'Enable additional transfers','Nama remote rclone':'rclone remote name','Subfolder / prefix tujuan':'Destination subfolder / prefix','Simpan tujuan penyimpanan':'Save storage destination','Uji koneksi tujuan':'Test destination connection','Coba ulang upload gagal':'Retry failed uploads','Antrean upload':'Upload queue',
  'Kredensial kosong mempertahankan kredensial tersimpan untuk tujuan yang sama. Kredensial baru hanya dikirim ke engine lokal.':'Leave credentials blank to retain stored credentials for the same destination. New credentials are sent only to the local engine.',
  'Buat backup sekarang':'Create backup now','Backup otomatis setiap 24 jam':'Automatic backup every 24 hours','Retensi backup (hari)':'Backup retention (days)','Simpan jadwal backup':'Save backup schedule','Backup terakhir':'Last backup','Belum ada backup':'No backups yet','Verifikasi backup':'Verify backup','Panduan pemulihan':'Recovery instructions','Belum tersedia':'Unavailable','Layanan monitoring':'Monitoring service','Model detektor':'Detector model','Perangkat inferensi':'Inference device','Versi skema database':'Database schema version','Kesalahan terakhir':'Last error','Perintah diterima oleh engine.':'Command accepted by the engine.',
  'Hentikan aplikasi dan service sebelum memulihkan database. Jalankan perintah ini dari folder instalasi, lalu mulai ulang aplikasi setelah hasil terverifikasi.':'Stop the app and service before restoring the database. Run this command from the installation folder and restart the app after verification succeeds.',
  'Ringkasan':'Overview','Pemantauan Live':'Live Monitoring','Workstation':'Workstations','Laporan':'Reports','Pengaturan':'Settings',
  'Lokasi':'Location','Nama lokasi':'Site name','Zona waktu':'Time zone','Bahasa':'Language','Simpan pengaturan':'Save settings',
  'Pengaturan lokal disimpan.':'Local settings saved.','Engine belum terhubung':'Engine disconnected',
  'Koneksi kamera, rekaman, dan pengaturan engine tersedia saat aplikasi terhubung ke layanan Python.':'Camera connections, recordings, and engine settings are available when connected to the Python service.',
  'Belum ada kamera':'No cameras added','Tambah kamera':'Add camera','Edit kamera':'Edit camera','Nama kamera':'Camera name','Alamat RTSP':'RTSP address','Target inferensi (FPS)':'Target inference (FPS)',
  'Konfigurasi disimpan di browser. Hubungkan layanan Python untuk membuka stream kamera.':'Configuration is saved in this browser. Connect the Python service to open camera streams.',
  'Batal':'Cancel','Simpan kamera':'Save camera','Daftar kamera':'Camera list','Cari kamera':'Search cameras','Status koneksi':'Connection status','Semua status':'All statuses',
  'Terhubung':'Connected','Observasi terganggu':'Observation interrupted','Tidak terhubung':'Disconnected','Menyambungkan':'Connecting','Nonaktif':'Disabled',
  'Tidak ada hasil':'No results','Fokus':'Focus','Zona':'Zones','Deteksi':'Detection','Detail kamera':'Camera details','Layar penuh semua kamera':'Full screen all cameras','Keluar layar penuh':'Exit full screen',
  'Kembali ke grid':'Back to grid','Layar penuh':'Full screen','Koneksi':'Connection','Target inferensi':'Target inference','Edit konfigurasi':'Edit configuration',
  'Belum ada workstation':'No workstations added','Tambahkan kamera sebelum mengatur zona workstation.':'Add a camera before configuring workstation zones.',
  'Belum ada data observasi':'No observation data','Ubah periode dan workstation':'Change period and workstation','Periode':'Period','Harian':'Daily','7 hari terakhir':'Last 7 days','Bulanan':'Monthly','Tahunan':'Yearly','Rentang tanggal':'Date range','Mulai':'From','Sampai':'To','Semua desk':'All workstations','Resolusi':'Resolution','Mingguan':'Weekly','Sumber':'Source','Interval detail':'Detailed intervals','Agregat kalender':'Calendar aggregates','Terapkan filter':'Apply filters','Ekspor':'Export',
  'Kamera terdaftar':'Registered cameras','Buka monitoring':'Open monitoring','Aktivitas konfigurasi':'Configuration activity','Belum ada event':'No events','Belum ada data':'No data',
};
const Context=createContext({language:'id',setLanguage:()=>{},t:value=>value});
export function LanguageProvider({children}) {
  const [language,setLanguage]=useState(()=>{try{return localStorage.getItem('cctv-language')==='en'?'en':'id';}catch{return 'id';}});
  useEffect(()=>{document.documentElement.lang=language;try{localStorage.setItem('cctv-language',language);}catch{}},[language]);
  const t=value=>typeof value==='string'&&language==='en'?(english[value]||value):value;
  return <Context.Provider value={{language,setLanguage,t}}>{children}</Context.Provider>;
}
export const useLanguage=()=>useContext(Context);
