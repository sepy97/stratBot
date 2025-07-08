import pandas as pd
import numpy as np
from sklearn.preprocessing import OrdinalEncoder
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score
import re
import time
from sklearn.feature_selection import mutual_info_regression
from xgboost import XGBRegressor
import shap
from xgboost import plot_tree
import matplotlib.pyplot as plt

# ==== Helper: Extract scenario combo from full_combo ====
def parse_scenario(combo_str):
    try:
        left, right = combo_str.split('-')
        left_match = re.match(r'1|2U|2D|3', left)
        right_match = re.match(r'1|2U|2D|3', right)
        if not right_match or not left_match:
            return None
        
        return f"{left_match.group(0)}-{right_match.group(0)}"
    except Exception:
        return None
def extract_tfc(combo_str):
    try:
        right = combo_str.split('-')[1]
        return 'G' if 'G' in right.lower() else 'R'
    except Exception:
        return None

def extract_shape(combo_str):
    left = combo_str.split('-')
    return left[0][-1] if left[0] else None

# === STEP 3: Function to analyze one direction ===
# Use random forest model to get feature importance and permulation importance
def analyze_RandomForest(df_dir, direction_label, features, target_col='gain %'):
    df_dir = df_dir.dropna(subset=features + [target_col])
    
    encoder = OrdinalEncoder()
    X_encoded = encoder.fit_transform(df_dir[features])
    X = pd.DataFrame(X_encoded, columns=features)
    y = df_dir[target_col]
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(X_encoded, y, test_size=0.2, random_state=42)

    model = RandomForestRegressor(n_estimators=200, random_state=42)
    model.fit(X_train, y_train)
    print(f"\n=== {direction_label.upper()} Direction Analysis - Random Forest ===")
    
    # Evaluate
    y_pred = model.predict(X_test)
    print("R² Score:", r2_score(y_test, y_pred))
    
    importances = model.feature_importances_
    rf_df = pd.DataFrame({'feature': features, 'importance': importances}).sort_values(by='importance', ascending=False)
    print("\n=== Feature Importance ===")
    print(rf_df)

    # Retrain the model on the full dataset for permutation importance
    model = RandomForestRegressor(n_estimators=200, random_state=42)
    model.fit(X, y)
    result = permutation_importance(model, X, y, n_repeats=10, random_state=42, n_jobs=-1)
    importance_df = pd.DataFrame({
        'feature': features,
        'importance_mean': result.importances_mean,
        'importance_std': result.importances_std
    }).sort_values(by='importance_mean', ascending=False)
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
    #output_csv = f"/Users/ilyatoytman/Git/stratBot/Trades/feature_importance_{direction_label}_{timestamp}.csv"
    #importance_df.to_csv(output_csv, index=False)
    #print(f"\nSaved {direction_label} feature importance to: {output_csv}")
    print("\n=== Permutation Importance ===")
    print(importance_df)

def analyze_grouping(df_dir, direction_label, group_cols, MIN_TRADES=5, target_col='gain %'):
    df_dir = df_dir.dropna(subset=group_cols + [target_col])
    
    # Group and aggregate
    grouped = (
        df_dir
        .groupby(group_cols)
        .agg(avg_gain=('gain %', 'mean'), std = ('gain %', 'std'), count=('gain %', 'size'))
        .reset_index()
    )
    
    # Filter by minimum trades
    grouped = grouped[grouped['count'] >= MIN_TRADES]
    
    # Sort by gain
    grouped = grouped.sort_values(by='avg_gain', ascending=False)
    
    # Add Sharpe ratio
    grouped['sharpe'] = grouped['avg_gain'] / grouped['std']

    # Print top results
    print(f"\n=== {direction_label.upper()} Direction Analysis - Simple Grouping ===")
    print(grouped.head(10))
    # Save
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
    output_csv = f"/Users/ilyatoytman/Git/stratBot/Trades/top_scenarios_by_gain_{direction_label}_{timestamp}.csv"
    #grouped.to_csv(output_csv, index=False)
    #print(f"\nSaved {direction_label} results to {output_csv}")

def analyze_XGBoost(df_dir, direction_label, features, target_col='gain %'):    
    df_dir = df_dir.dropna(subset=features + [target_col])
    
    encoder = OrdinalEncoder()
    X_encoded = encoder.fit_transform(df_dir[features])
    X = pd.DataFrame(X_encoded, columns=features)
    y = df_dir[target_col]
    
    model = XGBRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
        verbosity=0
    )
    
    model.fit(X, y)
    
    print(f"\n=== {direction_label.upper()} Direction Analysis - XGBoost ===")
    
    # Evaluate
    y_pred = model.predict(X)
    print("R² Score:", r2_score(y, y_pred))
    
    # Feature importance
    importances = model.feature_importances_
    importance_df = pd.DataFrame({'feature': features, 'importance': importances}).sort_values(by='importance', ascending=False)
    #importance_df = importance_df.sort_values(by='importance', ascending=False)
    print("\n=== Feature Importance ===")
    print(importance_df)
    
    # Save CSV
    output_csv = f"xgboost_feature_importance_{direction_label}.csv"
    #importance_df.to_csv(output_csv, index=False)
    #print(f"Saved feature importance to {output_csv}")
    # === Analyze top-performing combos ===
    print("\n=== XGBoost Feature Importance ===")
    N_feature = 6
    top_features = importance_df['feature'].head(N_feature).tolist()
    print(f"\nTop {N_feature} features for {direction_label}: {top_features}")

    grouped = (
        df_dir.groupby(top_features)
              .agg(avg_gain=('gain %', 'mean'), count=('gain %', 'size'))
              .reset_index()
    )
    grouped = grouped[grouped['count'] >= MIN_TRADES]
    grouped_sorted = grouped.sort_values(by='avg_gain', ascending=False)
    print (f"\n=== Top Combos for {direction_label} ===")
    print(grouped_sorted.head(10))
    # Save
    combo_csv = f"top_combos_{direction_label}.csv"
    #grouped_sorted.to_csv(combo_csv, index=False)
    #print(f"Saved top combos to {combo_csv}")
    #print(grouped_sorted.head(10))
    # === Extract and plot a decision tree from the XGBoost model ===
    print(f"\n=== Decision Tree (Tree #0) for {direction_label} ===")
    plt.figure(figsize=(30, 10))
    plot_tree(model, num_trees=0, rankdir='LR')
    plt.title(f"Tree #0 - {direction_label} direction")
    plt.show()

    # === SHAP analysis ===
    print(f"\n=== SHAP Summary Plot for {direction_label} ===")
    explainer = shap.Explainer(model)
    shap_values = explainer(X)

    shap.summary_plot(shap_values, X, feature_names=features, show=True)

# === STEP 1: Load your trade data ===
# Replace this with the path to your dataset
df = pd.read_csv("/Users/ilyatoytman/Git/stratBot/Trades/trades_20250101_20250430_NASDAQ100_2025_BasicDailyAS_2025-06-27_12-13-38.csv")  # Replace with your file path
# ==== Extract features from each timeframe ====
timeframes = ['d', 'w', 'm', 'q', 'y']
for tf in timeframes:
    df[f'{tf}_scenario'] = df[tf].apply(parse_scenario)
    df[f'{tf}_tfc'] = df[tf].apply(extract_tfc)
    df[f'{tf}_shape'] = df[tf].apply(extract_shape)

# ==== Filter out bad rows ====
# === STEP 2: Define relevant features ===
MIN_TRADES = 5  # Minimum number of trades per group to consider

# These are your encoded Strat features by timeframe (adjust as needed)
feature_cols = []
for tf in timeframes:
    feature_cols += [f'{tf}_scenario', f'{tf}_tfc', f'{tf}_shape']
# Target
target_col = 'gain %'
#df = df.dropna(subset=feature_cols + target_col)
# Drop rows with missing values in important columns
df = df.dropna(subset=feature_cols + [target_col])
direction_col = 'direction'  # Should contain values like 'long' or 'short'
df[direction_col] = df[direction_col].str.lower()  # Normalize direction column
# ==== Prepare for modeling ====
X_raw = df[feature_cols]
y = df[target_col].values
encoder = OrdinalEncoder()
X = encoder.fit_transform(X_raw)

# ==== Mutual Information ====
# This is helpful for finding features that are useless (lowest scores)
mi = mutual_info_regression(X, y, discrete_features=True)
mi_df = pd.DataFrame({'feature': feature_cols, 'mutual_info': mi}).sort_values(by='mutual_info', ascending=False)
print("\n=== Mutual Information ===")
print(mi_df)

# ==== Random Forest Importance ====
#model = RandomForestRegressor(n_estimators=100, random_state=42)
#model.fit(X, y)
#importances = model.feature_importances_
#rf_df = pd.DataFrame({'feature': feature_cols, 'importance': importances}).sort_values(by='importance', ascending=False)
#print("\n=== Random Forest Feature Importance ===")
#print(rf_df)

# ==== Grouping by high-level feature combos (optional) ====
analyze_grouping(df, 'all', feature_cols)
#analyze_RandomForest(df, 'all', feature_cols)
analyze_XGBoost(df, 'all', feature_cols)

for direction in ['long', 'short']:
    df_dir = df[(df['direction'] == direction)].copy()
    if df_dir.empty:
        print(f"No data for direction: {direction}")
        continue
    #analyze_RandomForest(df_dir, direction, feature_cols)
    analyze_grouping(df_dir, direction, feature_cols)
    analyze_XGBoost(df_dir, direction, feature_cols)


'''
df_encoded = pd.DataFrame(X, columns=feature_cols)
df_encoded[target_col] = y
grouped = df_encoded.groupby(feature_cols)[target_col].agg(['mean', 'count', 'std']).reset_index()
grouped = grouped[grouped['count'] >= 5]
# Decode numeric combos back to original symbolic values
decoded = encoder.inverse_transform(grouped[feature_cols])
decoded_df = pd.DataFrame(decoded, columns=feature_cols)
# Combine decoded symbolic combos with aggregated stats (mean, count, std)
grouped_final = pd.concat([decoded_df, grouped[['mean', 'count', 'std']].reset_index(drop=True)], axis=1)
grouped_final['sharpe'] = grouped_final['mean'] / grouped_final['std']
best = grouped_final.sort_values(by='mean', ascending=False).head(5)
print("\n=== Top Performing Indicator Combos ===")
print(best)
# Export to CSV
output_csv_path = '/Users/ilyatoytman/Git/stratBot/Trades/BasicDailyAS_top_indicator_combos_decoded.csv'
grouped_final.to_csv(output_csv_path, index=False)
print(f"Decoded combos with stats saved to {output_csv_path}")
'''

# === Config ===


# Results:
# Long: D 2d-2u, W 1-2D, M 2D-2D
# Short: D 2U-2D