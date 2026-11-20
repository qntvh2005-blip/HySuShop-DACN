"""Compatibility decisions reviewed against the retained source by item ID."""

# These products work across phone families when the relevant cable, Bluetooth
# support, screen type, surface, or dimensions are suitable.
UNIVERSAL_ITEMS = frozenset("""
    B00HY3HT1Y B07YN7QM22 B07JH63XNY B07L1CRPTS
    B0088U4YAG B079FYG5TC B07J6FWK57 B07VQ8GS26 B086HJYR1S B0BV19D1VF B0BX6V8SP3
    B07DCRVBYX B0C575KCXJ B0CF4P6RVC
    B007GNNH3Q B00HRKI5V2 B00HUIL310 B00JNJPS4W B00PGJWYJ0 B00VQ93RIG B012EI4J3O
    B01780KZMW B01B6K2GDQ B01F7KNJDM B01G0X56YU B01M0DUVZV B01M0UVZI0 B01M4J0G7I
    B01MR4AO9D B01N210GDQ B01NACB36Z B06Y42RKPF B0773F8S74 B077MTNV41 B07K2VX92N
    B07S5DRV1M B099KLB756 B09JNK59QM B09KD3N8Y4 B09KZH4PSY B0B152TZKR B0BGJ26GC9
    B0BJ5WJY34 B0BMPCRSQQ B0BYTRS2N2 B0C2L6DH7B B0C3C2GXM7 B0C6L5J1JV B0C6NJS645
    B0C995ZD3J B06VXYPWMC B06WD83Z36 B07F27VDMX B07HCZLML5 B07K124GHB B09JHN94XD
    B0BTYHJZR7 B0BXWR6HPQ B071GVLZCQ B072KNBV21
    B005NF5NTK B00FDK2G2C B00MFVNLXK B00P7N0320 B01422TC14 B01B14ANLY B01CU1EC6Y
    B01JIYWUBA B06XQV5DDP B072MH1434 B075WPN5HX B07PFMJ3XG B088GTNGSX B095C28DXK
    B09Y8SH48J B0BTYHPVNN B0BZ8FPHW5
    B0092KJ9BU B00DQ5RHK2 B00W3TAMG8 B01JA9J6UQ B01M2ZOLLP B08HYDP59S B092DFWB3N
    B0C786CPSM B079FH32V1 B07C16TCL8 B084TMLSY8 B09XDSZ6C1 B0BXST372J B0BYS7ZYJ1
    B0C4T6NPBG B0059KTEBC B0064REJ3C B076HFJJZP B076HHRX7C B07QGPS354 B09WVRFMCX
    B09XBWZB8N B004ZGLM5W B07BLKHJF1 B07BNT3NM4 B07NWC3L95 B09LM4X68F B0BTBXYD7N
    B0CC3QMHC9 B0784P9DBK B005CG2ATQ B01JLXTQ5G B074481TQT B07DDQPD74 B0BYJ8ZVWH
""".split())

# Model names stated in the product features, specifications, or description.
# Leave out unspecified generations and models that need a separate receiver.
REVIEWED_DEVICE_NAMES = {
    "B00CM0PL1E": {"Apple": "iPhone 3G|iPhone 3GS|iPhone 4|iPhone 4s"},
    "B00GM0OZ4O": {"Samsung": "Galaxy S2", "Google": "Nexus 4"},
    "B00IHS1XI0": {"Apple": "iPhone 8|iPhone X", "Samsung": "Galaxy S7|Galaxy S8|Galaxy S9"},
    "B00J9Z0L42": {"Apple": "iPhone 4|iPhone 4s|iPhone 5|iPhone 5s|iPhone 5c"},
    "B0143GESZO": {
        "Apple": "iPhone 8|iPhone 8 Plus|iPhone X",
        "Samsung": "Galaxy Note 5|Galaxy Note 8|Galaxy S6|Galaxy S7|Galaxy S8|Galaxy S9",
        "Google": "Nexus 4|Nexus 5|Nexus 6",
    },
    "B015CMD692": {"Samsung": "Galaxy Note 2|Galaxy S3|Galaxy S4|Galaxy S5"},
    "B01A6L85CC": {"Apple": "iPhone 6|iPhone 6s|iPhone 6 Plus|iPhone 7|iPhone 7 Plus|iPhone 8|iPhone 8 Plus|iPhone X|iPhone XS"},
    "B01BMDQ9U8": {"Samsung": "Galaxy Note 5|Galaxy S6 Edge Plus"},
    "B07586VK1V": {
        "Apple": "iPhone 5|iPhone 5s|iPhone 5c|iPhone 6|iPhone 6 Plus|iPhone 6s|iPhone 6s Plus|"
        "iPhone 7|iPhone 7 Plus|iPhone 8|iPhone 8 Plus|iPhone X|iPhone XR|iPhone XS|iPhone XS Max|"
        "iPhone 11|iPhone 11 Pro|iPhone 11 Pro Max|iPhone 12|iPhone 12 Mini|iPhone 12 Pro|"
        "iPhone 12 Pro Max|iPhone 13|iPhone 13 Mini|iPhone 13 Pro|iPhone 13 Pro Max|"
        "iPhone 14|iPhone 14 Plus|iPhone 14 Pro|iPhone 14 Pro Max|"
        "iPhone SE (2016)|iPhone SE (2020)|iPhone SE (2022)",
    },
    "B075V234VL": {
        "Apple": "iPhone 8|iPhone 8 Plus|iPhone X",
        "Samsung": "Galaxy S8|Galaxy Note 8|Galaxy Note 5|Galaxy S6 Edge Plus",
    },
    "B07GBN8HBN": {"Apple": "iPhone 8|iPhone X", "Samsung": "Galaxy S9|Galaxy Note 9"},
    "B0B24W73QH": {"Apple": "iPhone 12|iPhone 13|iPhone 13 Mini|iPhone 14|iPhone 14 Plus|iPhone 14 Pro|iPhone 14 Pro Max"},
    "B0B86Z99SL": {
        "Apple": "iPhone 8|iPhone 8 Plus|iPhone X|iPhone XR|iPhone XS|iPhone XS Max|"
        "iPhone SE (2020)|iPhone 11|iPhone 11 Pro|iPhone 11 Pro Max|iPhone 12|iPhone 12 Mini|"
        "iPhone 12 Pro|iPhone 12 Pro Max|iPhone 13|iPhone 13 Mini|iPhone 13 Pro|"
        "iPhone 13 Pro Max|iPhone 14|iPhone 14 Plus|iPhone 14 Pro|iPhone 14 Pro Max",
        "Samsung": "Galaxy S6|Galaxy S6 Edge|Galaxy S6 Edge Plus|Galaxy S8|Galaxy S8 Plus|"
        "Galaxy S9|Galaxy S9 Plus|Galaxy S10|Galaxy S10 Plus|Galaxy S10e|Galaxy S20|"
        "Galaxy S20 Plus|Galaxy Note 10|Galaxy Note 10 Plus|Galaxy Note 20",
        "Google": "Pixel 3|Pixel 3 XL|Pixel 4|Pixel 4 XL|Nexus 4|Nexus 5",
    },
}
