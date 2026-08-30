import pandas as pd

# Load dataset from data folder
df = pd.read_csv('data/daraz_reviews_labeled.csv', encoding='utf-8', encoding_errors='replace')

# Drop duplicates & filter short reviews
df = df.drop_duplicates(subset=['Sentiments', 'Reviews'])
df = df[df['Reviews'].str.len() > 5]

# Save cleaned dataset in data folder
df.to_csv('data/daraz_reviews_cleaned.csv', index=False)
print(f'Cleaned: {len(df)} rows remaining')