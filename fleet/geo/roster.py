"""Static, deterministic HCM customer roster for the real-map world. Same tuple
shape as scenarios.cust_specs:
    (id, type, lat, lng, name, orders, priority, tw_start_h, tw_end_h, sla_h)
Real central-HCM coordinates spread across districts; ids stay C001.. so the
flood-prone parallel edge for C001 keeps its meaning."""

HCM_CUSTOMERS = [
    ("C001", "supermarket",       10.8050, 106.6300, "BigC Mien Dong",
     {"SKU001": 10, "SKU002": 5}, 1, 1, 3, 4),
    ("C002", "market",            10.7765, 106.6870, "Cho Ben Thanh",
     {"SKU001": 20}, 2, 1.5, 3.5, 5),
    ("C003", "convenience_store", 10.8150, 106.6150, "MiniMart Le Loi",
     {"SKU002": 15, "SKU003": 8}, 3, 2, 4, 6),
    ("C004", "restaurant",        10.8300, 106.6400, "Nha hang A Chau",
     {"SKU003": 30}, 2, 1.75, 4, 5.5),
    ("C005", "supermarket",       10.7689, 106.6918, "Co.opmart Cong Quynh",
     {"SKU001": 12, "SKU003": 6}, 2, 1, 4, 5),
    ("C006", "mall",              10.7785, 106.7008, "Vincom Dong Khoi",
     {"SKU002": 18}, 1, 2, 5, 6),
    ("C007", "market",            10.7906, 106.6904, "Cho Tan Dinh",
     {"SKU001": 14}, 3, 1.5, 4, 5.5),
    ("C008", "convenience_store", 10.7820, 106.6820, "Circle K Hai Ba Trung",
     {"SKU002": 9}, 4, 2, 6, 7),
    ("C009", "restaurant",        10.8010, 106.6650, "Quan An Ngon Q3",
     {"SKU003": 22}, 2, 1, 3.5, 5),
    ("C010", "supermarket",       10.7960, 106.6780, "Satra Mart Vo Thi Sau",
     {"SKU001": 16, "SKU002": 7}, 2, 2, 5, 6),
    ("C011", "convenience_store", 10.7700, 106.6790, "GS25 Nguyen Cu Trinh",
     {"SKU003": 11}, 3, 1.5, 4.5, 5.5),
    ("C012", "market",            10.7540, 106.6660, "Cho Nguyen Tri Phuong",
     {"SKU001": 25}, 3, 1, 4, 6),
    ("C013", "mall",              10.7830, 106.6940, "Diamond Plaza",
     {"SKU002": 20, "SKU003": 10}, 1, 2, 5, 6),
    ("C014", "restaurant",        10.8120, 106.6520, "Nha hang Hoa Sen",
     {"SKU003": 28}, 2, 1.75, 4, 5.5),
    ("C015", "supermarket",       10.7610, 106.6820, "Bach Hoa Xanh Tran Hung Dao",
     {"SKU001": 13, "SKU002": 6}, 3, 1, 4, 5),
    ("C016", "convenience_store", 10.8240, 106.6260, "FamilyMart Phan Van Tri",
     {"SKU002": 8}, 4, 2, 6, 7),
    ("C017", "market",            10.7880, 106.6620, "Cho Vuon Chuoi",
     {"SKU001": 17}, 3, 1.5, 4, 5.5),
    ("C018", "restaurant",        10.8060, 106.6840, "Nha hang Que Huong",
     {"SKU003": 24}, 2, 1, 3.5, 5),
]
