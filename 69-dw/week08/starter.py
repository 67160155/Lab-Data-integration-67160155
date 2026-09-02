from pathlib import Path
import json
import pandas as pd
import numpy as np

# กำหนด Path สำหรับโฟลเดอร์ data และ output (รองรับทั้งการรันแบบ .py และ .ipynb)
try:
    BASE_DIR = Path(__file__).resolve().parent
except NameError:
    BASE_DIR = Path.cwd()

DATA = BASE_DIR / "data" if (BASE_DIR / "data").exists() else BASE_DIR
OUTPUT = BASE_DIR / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)

print("เริ่มทำ Data Integration...")

# ==========================================
# TODO 1: Extract ข้อมูลจาก CSV, Excel และ JSON + Profiling
# ==========================================
print("1. กำลังโหลดข้อมูลและสำรวจคุณภาพ (Extract & Profiling)...")
df_cust = pd.read_csv(DATA / "customers_crm.csv")
df_jan = pd.read_csv(DATA / "orders_2026_01.csv")
df_feb = pd.read_csv(DATA / "orders_2026_02.csv")
df_prod = pd.read_excel(DATA / "product_master.xlsx")

# อ่าน payments.json และกระจาย Nested Dictionary ออกเป็นคอลัมน์
with open(DATA / "payments.json", "r", encoding="utf-8") as f:
    df_pay = pd.json_normalize(json.load(f))

# Profiling ข้อมูลเบื้องต้น (ตามเกณฑ์ข้อที่ 1)
print(f" - Raw Customers: {len(df_cust)} แถว")
print(f" - Raw Jan Orders: {len(df_jan)} แถว")
print(f" - Raw Feb Orders: {len(df_feb)} แถว")
print(f" - Raw Products: {len(df_prod)} แถว")
print(f" - Raw Payments: {len(df_pay)} แถว")


# ==========================================
# TODO 2: ทำ schema alignment ของไฟล์ orders สองเดือน แล้ว concat + อธิบาย Schema Drift
# ==========================================
print("\n2. ปรับโครงสร้างข้อมูล (Schema Alignment) และรวมข้อมูลคำสั่งซื้อ...")

# ตรวจสอบและแสดง Schema Drift ก่อนแก้ไข (ตามเกณฑ์ข้อที่ 2)
print("--- [Schema Drift Check] ---")
print("คอลัมน์ Jan:", df_jan.columns.tolist())
print("คอลัมน์ Feb (ก่อน Rename):", df_feb.columns.tolist())
print(">> อธิบาย Schema Drift: เดือน Feb ใช้ชื่อคอลัมน์ต่างกัน ได้แก่ 'ordered_at', 'qty', 'discount_pct'")

feb_mapping = {
    'ordered_at': 'order_date',
    'qty': 'quantity',
    'discount_pct': 'discount'
}
df_feb_aligned = df_feb.rename(columns=feb_mapping)

df_orders = pd.concat([df_jan, df_feb_aligned], ignore_index=True)
initial_order_count = len(df_orders)


# ==========================================
# TODO 3: Clean/standardize/deduplicate และสร้าง data quality report
# ==========================================
print("\n3. ทำความสะอาดและสร้าง Data Quality Report...")

# --- Clean Customers ---
if 'full_name' in df_cust.columns:
    df_cust = df_cust.rename(columns={'full_name': 'customer_name'})

if 'email' in df_cust.columns:
    df_cust['email'] = df_cust['email'].astype(str).str.strip().str.lower()
    
if 'customer_name' in df_cust.columns:
    df_cust['customer_name'] = df_cust['customer_name'].astype(str).str.strip()

# ปรับชื่อจังหวัดให้เป็นมาตรฐาน (แก้สระเอ 2 ตัว 'เเ' -> 'แ' และแปลงชื่อภาษาอังกฤษเป็นภาษาไทย)
if 'province' in df_cust.columns:
    df_cust['province'] = df_cust['province'].astype(str).str.strip().str.replace('\u0e40\u0e40', '\u0e41')
    
    province_map = {
        'กทม': 'กรุงเทพมหานคร',
        'กทม.': 'กรุงเทพมหานคร',
        'กรุงเทพฯ': 'กรุงเทพมหานคร',
        'กรุงเทพ': 'กรุงเทพมหานคร',
        'bangkok': 'กรุงเทพมหานคร',
        'phuket': 'ภูเก็ต',
        'rayong': 'ระยอง',
        'chiang mai': 'เชียงใหม่',
        'chiangmai': 'เชียงใหม่',
        'chonburi': 'ชลบุรี',
        'chon buri': 'ชลบุรี',
        'khon kaen': 'ขอนแก่น',
        'khonkaen': 'ขอนแก่น'
    }
    df_cust['province'] = df_cust['province'].apply(
        lambda x: province_map.get(str(x).lower(), x) if pd.notna(x) else x
    )

df_cust = df_cust.drop_duplicates(subset=['customer_id'])

# --- Clean Payments Schema ---
df_pay = df_pay.rename(columns={
    'payment.method': 'payment_method',
    'payment.status': 'payment_status'
})

# --- Clean Orders ---
dup_orders_count = df_orders.duplicated(subset=['order_id']).sum()
df_orders = df_orders.drop_duplicates(subset=['order_id'])

# แปลงวันที่ให้เป็นรูปแบบมาตรฐาน YYYY-MM-DD
df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], format="mixed", dayfirst=True).dt.strftime('%Y-%m-%d')

# แปลงส่วนลดให้อยู่ในรูปทศนิยม
def parse_discount(val):
    if pd.isna(val): 
        return 0.0
    val_str = str(val).replace('%', '').strip()
    try:
        num = float(val_str)
        return num / 100.0 if num >= 1.0 else num
    except ValueError:
        return 0.0

df_orders['discount'] = df_orders['discount'].apply(parse_discount)

# กรอง Quantity (เก็บจำนวนที่ > 0)
invalid_qty_count = (df_orders['quantity'] <= 0).sum()
df_orders = df_orders[df_orders['quantity'] > 0]

# --- สร้าง Data Quality Report ---
dq_data = [
    {'Metric': 'Total Orders (Raw)', 'Value': initial_order_count},
    {'Metric': 'Duplicate Orders Removed', 'Value': dup_orders_count},
    {'Metric': 'Invalid Quantity Removed (<= 0)', 'Value': invalid_qty_count},
    {'Metric': 'Cleaned Orders', 'Value': len(df_orders)}
]
df_dq_report = pd.DataFrame(dq_data)
df_dq_report.to_csv(OUTPUT / "data_quality_report.csv", index=False, encoding='utf-8-sig')


# ==========================================
# TODO 4: Enrich ด้วย customer, product และ payment master + Validate Unmatched Records
# ==========================================
print("\n4. เชื่อมโยงข้อมูลคำสั่งซื้อ ลูกค้า สินค้า และการชำระเงิน...")
df_merged = df_orders.merge(df_pay[['order_id', 'payment_method', 'payment_status']], on='order_id', how='left')
df_merged = df_merged.merge(df_prod[['product_id', 'product_name', 'category', 'standard_price']], on='product_id', how='left')
df_merged = df_merged.merge(df_cust, on='customer_id', how='left')

# ตรวจสอบ Unmatched Records (ตามเกณฑ์ข้อที่ 4)
print("--- [Validation Check - Unmatched Records] ---")
unmatched_cust = df_merged['customer_name'].isnull().sum()
unmatched_prod = df_merged['product_name'].isnull().sum()
unmatched_pay = df_merged['payment_status'].isnull().sum()
print(f" - Unmatched Customers: {unmatched_cust} รายการ")
print(f" - Unmatched Products: {unmatched_prod} รายการ")
print(f" - Unmatched Payments: {unmatched_pay} รายการ")

# หาก unit_price ในคำสั่งซื้อว่าง ให้ใช้ standard_price จาก product_master
if 'standard_price' in df_merged.columns:
    df_merged['unit_price'] = df_merged['unit_price'].fillna(df_merged['standard_price'])


# ==========================================
# TODO 5: Validate business rules ก่อนคำนวณยอดขาย
# ==========================================
print("\n5. คำนวณยอดขายสุทธิ...")
df_merged['gross_sales'] = df_merged['quantity'] * df_merged['unit_price']
df_merged['discount_amount'] = df_merged['gross_sales'] * df_merged['discount']
df_merged['net_sales'] = df_merged['gross_sales'] - df_merged['discount_amount']


# ==========================================
# TODO 6: Load dim_customer.csv, dim_product.csv และ fact_sales.csv
# ==========================================
print("\n6. บันทึกไฟล์ Dimension และ Fact tables...")
# 6.1 dim_customer
cust_cols = ['customer_id', 'customer_name', 'email', 'phone', 'province', 'signup_date']
for col in cust_cols:
    if col not in df_cust.columns:
        df_cust[col] = np.nan
dim_customer = df_cust[cust_cols]
dim_customer.to_csv(OUTPUT / "dim_customer.csv", index=False, encoding='utf-8-sig')

# 6.2 dim_product
df_prod_renamed = df_prod.rename(columns={'standard_price': 'unit_price'})
prod_cols = ['product_id', 'product_name', 'category', 'unit_price']
for col in prod_cols:
    if col not in df_prod_renamed.columns:
        df_prod_renamed[col] = np.nan
dim_product = df_prod_renamed[prod_cols]
dim_product.to_csv(OUTPUT / "dim_product.csv", index=False, encoding='utf-8-sig')

# 6.3 fact_sales
fact_cols = [
    'order_id', 'order_date', 'customer_id', 'product_id', 'payment_method', 'payment_status',
    'quantity', 'unit_price', 'discount', 'net_sales'
]
fact_sales = df_merged[fact_cols]
fact_sales.to_csv(OUTPUT / "fact_sales.csv", index=False, encoding='utf-8-sig')


# ==========================================
# TODO 7: สร้าง summary_by_province.csv และ summary_by_category.csv
# ==========================================
print("\n7. สร้างและบันทึกไฟล์ Summary...")
# กรองเฉพาะรายการที่ชำระเงินสำเร็จ (PAID)
df_completed = df_merged[df_merged['payment_status'].astype(str).str.upper() == 'PAID']

# 7.1 summary_by_province
summary_prov = df_completed.groupby('province').agg(
    total_orders=('order_id', 'nunique'),
    total_quantity=('quantity', 'sum'),
    total_net_sales=('net_sales', 'sum')
).reset_index().sort_values('total_net_sales', ascending=False)
summary_prov.to_csv(OUTPUT / "summary_by_province.csv", index=False, encoding='utf-8-sig')

# 7.2 summary_by_category
summary_cat = df_completed.groupby('category').agg(
    total_orders=('order_id', 'nunique'),
    total_quantity=('quantity', 'sum'),
    total_net_sales=('net_sales', 'sum')
).reset_index().sort_values('total_net_sales', ascending=False)
summary_cat.to_csv(OUTPUT / "summary_by_category.csv", index=False, encoding='utf-8-sig')

print("\nเสร็จสิ้น! ไฟล์ผลลัพธ์ทั้ง 6 ไฟล์ถูกบันทึกไว้ในโฟลเดอร์ 'output' เรียบร้อยแล้ว")