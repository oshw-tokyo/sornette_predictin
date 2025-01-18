import os
import yfinance as yf
import numpy as np
from scipy.optimize import curve_fit
from scipy import stats  # 
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from sklearn.metrics import r2_score, mean_squared_error
import pandas as pd
import json

#
from analysis_logger import AnalysisLogger, get_latest_analyses

def ensure_output_dir(dir_name='analysis_results/temp'):
    """出力ディレクトリが存在しない場合は作成"""
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
    return dir_name

def download_stock_data(symbol, start_date, end_date):
    """
    Yahoo Financeから株価データをダウンロード
    """
    try:
        stock = yf.download(symbol, start=start_date, end=end_date)
        if stock.empty:
            print(f"警告: {symbol}のデータが空です。")
            return None
        return stock
    except Exception as e:
        print(f"警告: {symbol}のダウンロードに失敗しました: {str(e)}")
        return None

def prepare_data(stock_data):
    """
    分析用にデータを準備
    """
    # 終値を使用
    prices = stock_data['Close'].values
    # 時間を数値インデックスに変換
    times = np.arange(len(prices))
    return times, prices

def log_periodic_function(t, tc, m, omega, phi, A, B, C):
    """
    対数周期関数のモデル
    """
    # tをnumpy配列に変換
    t = np.asarray(t)
    # dtが負になる部分を除外
    dt = tc - t
    mask = dt > 0
    result = np.zeros_like(t, dtype=float)
    result[mask] = A + B * dt[mask]**m + C * dt[mask]**m * np.cos(omega * np.log(dt[mask]) + phi)
    return result

def fit_log_periodic(time, price, tc_guess):
    """
    対数周期関数のフィッティング
    """
    # データを1次元配列に変換
    time = np.asarray(time).ravel()
    price = np.asarray(price).ravel()
    
    # 初期値を調整
    mean_price = np.mean(price)
    std_price = np.std(price)
    
    # パラメータの初期値
    p0 = [
        tc_guess,      # tc
        0.33,          # m
        6.28,          # omega
        0,             # phi
        mean_price,    # A
        -std_price/2,  # B
        std_price/4    # C
    ]
    
    # フィッティングの境界条件
    bounds = (
        [tc_guess-50, 0.01, 1, -np.pi, mean_price*0.5, -np.inf, -np.inf],
        [tc_guess+50, 0.99, 20, np.pi, mean_price*1.5, np.inf, np.inf]
    )
    
    try:
        # フィッティングの実行
        popt, pcov = curve_fit(
            log_periodic_function, 
            time, 
            price, 
            p0=p0,
            bounds=bounds,
            maxfev=10000,
            method='trf'  # trust region reflective algorithm
        )
        return popt, pcov
    except (RuntimeError, ValueError) as e:
        print(f"フィッティングエラー: {e}")
        return None, None

def analyze_stock(symbol, start_date, end_date, tc_guess_days=30):
    """
    株価の対数周期性分析を実行
    """
    # データのダウンロード
    print(f"{symbol}のデータをダウンロード中...")
    stock_data = download_stock_data(symbol, start_date, end_date)
    
    # データの準備
    times, prices = prepare_data(stock_data)
    
    # tc_guessを設定（現在のデータ長から指定日数後）
    tc_guess = len(times) + tc_guess_days
    
    # フィッティング実行
    print("対数周期性分析を実行中...")
    popt, pcov = fit_log_periodic(times, prices, tc_guess)
    
    if popt is not None:
        tc, m, omega, phi, A, B, C = popt
        
        # 結果の表示
        print("\n分析結果:")
        print(f"予測される臨界時点: データ終了から約{tc - len(times):.1f}日後")
        print(f"べき指数 (m): {m:.3f}")
        print(f"角振動数 (omega): {omega:.3f}")
        print(f"位相 (phi): {phi:.3f}")
        print(f"振幅パラメータ A: {A:.2f}")
        print(f"振幅パラメータ B: {B:.2f}")
        print(f"振幅パラメータ C: {C:.2f}")
        
        # フィッティング曲線の生成
        t_fit = np.linspace(min(times), tc-1, 1000)
        price_fit = log_periodic_function(t_fit, *popt)
        
        # プロット
        plt.figure(figsize=(15, 10))
        
        # 実データのプロット
        plt.plot(times, prices, 'ko', label='実データ', markersize=2)
        
        # フィッティング曲線のプロット
        plt.plot(t_fit, price_fit, 'r-', label='予測モデル')
        
        # 臨界時点の表示
        plt.axvline(x=tc, color='g', linestyle='--', label='予測される臨界時点')
        
        # 日付ラベルの設定
        dates = stock_data.index
        plt.xticks(
            [0, len(times)-1, tc], 
            [dates[0].strftime('%Y-%m-01'), 
             dates[-1].strftime('%Y-%m-%d'),
             (dates[-1] + timedelta(days=int(tc - len(times)))).strftime('%Y-%m-%d')],
            rotation=45
        )
        
        plt.xlabel('日付')
        plt.ylabel('価格')
        plt.title(f'{symbol}の対数周期性分析')
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        
        # グラフを保存
        output_dir = ensure_output_dir(dir_name="analysis_results/plots")
        plt.savefig(os.path.join(output_dir, f'{symbol}_analysis.png'))
        plt.close()  # プロットを閉じる
        
        return popt, stock_data
    else:
        print("分析に失敗しました。")
        return None, stock_data

def validate_fit_quality(times, prices, popt, plot=True, symbol=None):
    """
    フィッティングの品質を評価
    """
    # 入力データを1次元配列に確実に変換
    times = np.asarray(times).ravel()
    prices = np.asarray(prices).ravel()
    
    # モデルによる予測値の計算
    predicted_prices = log_periodic_function(times, *popt)
    
    # 評価指標の計算
    r2 = r2_score(prices, predicted_prices)
    rmse = np.sqrt(mean_squared_error(prices, predicted_prices))
    
    # 残差の計算と1次元配列への変換
    residuals = (prices - predicted_prices).ravel()
    
    # 残差の正規性検定
    _, normality_p_value = stats.normaltest(residuals)
    
    # 残差から無限大やNaNを除去
    residuals = residuals[np.isfinite(residuals)]
    
    # 自己相関の計算（残差が空でないことを確認）
    if len(residuals) > 0:
        # 残差の分散が0でないことを確認
        variance = np.var(residuals)
        if variance > 0:
            autocorr = np.correlate(residuals, residuals, mode='full') / (len(residuals) * variance)
            autocorr = autocorr[len(autocorr)//2:]
        else:
            print("警告: 残差の分散が0です")
            autocorr = np.zeros(len(residuals))
    else:
        print("警告: 有効な残差データがありません")
        autocorr = np.array([])
    
    if plot:
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # 1. 実データvs予測値プロット
        axes[0,0].scatter(prices, predicted_prices, alpha=0.5)
        axes[0,0].plot([min(prices), max(prices)], [min(prices), max(prices)], 'r--')
        axes[0,0].set_xlabel('実際の価格')
        axes[0,0].set_ylabel('予測価格')
        axes[0,0].set_title('実際の価格 vs 予測価格')
        
        # 2. 残差プロット
        axes[0,1].scatter(times, residuals, alpha=0.5)
        axes[0,1].axhline(y=0, color='r', linestyle='--')
        axes[0,1].set_xlabel('時間')
        axes[0,1].set_ylabel('残差')
        axes[0,1].set_title('残差の時系列プロット')
        
        # 3. 残差のヒストグラム
        if len(residuals) > 0:
            axes[1,0].hist(residuals, bins=30, density=True, alpha=0.7)
            xmin, xmax = axes[1,0].get_xlim()
            x = np.linspace(xmin, xmax, 100)
            axes[1,0].plot(x, stats.norm.pdf(x, np.mean(residuals), np.std(residuals)), 'r-', lw=2)
            axes[1,0].set_xlabel('残差')
            axes[1,0].set_ylabel('頻度')
            axes[1,0].set_title('残差の分布')
        
        # 4. 自己相関プロット
        if len(autocorr) > 0:
            lags = np.arange(len(autocorr))
            axes[1,1].plot(lags, autocorr)
            axes[1,1].axhline(y=0, color='r', linestyle='--')
            axes[1,1].axhline(y=1.96/np.sqrt(len(times)), color='r', linestyle=':')
            axes[1,1].axhline(y=-1.96/np.sqrt(len(times)), color='r', linestyle=':')
            axes[1,1].set_xlabel('ラグ')
            axes[1,1].set_ylabel('自己相関')
            axes[1,1].set_title('残差の自己相関')
        
        plt.tight_layout()
        
        
        # ファイルを保存
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'fit_quality_{symbol}_{timestamp}.png' if symbol else f'fit_quality_{timestamp}.png'
        
        output_dir = ensure_output_dir(dir_name="analysis_results/plots")
        plt.savefig(os.path.join(output_dir, filename))
        plt.close()

    
    # 最大自己相関の計算（自己相関が存在する場合のみ）
    max_autocorr = np.max(np.abs(autocorr[1:])) if len(autocorr) > 1 else 0
    
    return {
        'R2': r2,
        'RMSE': rmse,
        'Residuals_normality_p': normality_p_value,
        'Max_autocorr': max_autocorr
    }

def check_stability(times, prices, window_size=30, step=5, data=None, symbol=None):
    """
    パラメータの安定性をチェック
    

    Returns:
    --------
    tuple:
        (tc_mean, tc_std, tc_cv, window_consistency)

    Parameters:
    -----------
    times : array-like
        時間データ
    prices : array-like
        価格データ
    window_size : int
        分析ウィンドウのサイズ（日数）
    step : int
        ウィンドウのスライド幅（日数）
    data : pandas.DataFrame
        元の株価データ（日付情報を取得するため）
    """
    tc_estimates = []
    windows = []
    
    for i in range(0, len(times) - window_size, step):
        window_times = times[i:i+window_size]
        window_prices = prices[i:i+window_size]
        
        tc_guess = window_times[-1] + 30
        
        try:
            popt, _ = fit_log_periodic(window_times, window_prices, tc_guess)
            if popt is not None:
                tc_estimates.append(popt[0])
                windows.append(window_times[-1])
        except:
            continue
    
    if tc_estimates:
        plt.figure(figsize=(12, 6))
        plt.plot(windows, tc_estimates, 'bo-')
        plt.xlabel('ウィンドウ終了時点')
        plt.ylabel('予測された臨界時点')
        plt.title('臨界時点予測の安定性分析')
        plt.grid(True)
        
        # グラフを保存
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'stability_{symbol}_{timestamp}.png' if symbol else f'stability_{timestamp}.png'
        
        output_dir = ensure_output_dir(dir_name="analysis_results/plots")
        plt.savefig(os.path.join(output_dir, filename))
        plt.close() # プロットを閉じる
        
        # 安定性の指標を計算
        tc_std = np.std(tc_estimates)
        tc_mean = np.mean(tc_estimates)
        tc_cv = tc_std / tc_mean  # 変動係数

        # 時間窓での一貫性を計算
        window_consistency = max(0, 1 - 2 * tc_cv) if tc_cv is not None else 0
        
        print(f"\n安定性分析結果:")
        print(f"臨界時点の平均: {tc_mean:.2f}")
        print(f"臨界時点の標準偏差: {tc_std:.2f}")
        print(f"変動係数: {tc_cv:.3f}")
        print(f"予測一貫性: {window_consistency:.3f}") 
        
        # 日付での表示を追加
        if data is not None:
            mean_days_from_end = tc_mean - len(times)
            predicted_mean_date = data.index[-1] + timedelta(days=int(mean_days_from_end))
            print(f"予測される平均的な臨界時点の日付: {predicted_mean_date.strftime('%Y年%m月%d日')}")
            
            # 標準偏差を考慮した予測範囲
            earliest_date = predicted_mean_date - timedelta(days=int(tc_std))
            latest_date = predicted_mean_date + timedelta(days=int(tc_std))
            print(f"予測範囲: {earliest_date.strftime('%Y年%m月%d日')} ～ {latest_date.strftime('%Y年%m月%d日')}")
        
        return tc_mean, tc_std, tc_cv, window_consistency
    else:
        print("安定性分析に失敗しました。")
        return None, None, None, None



def enhanced_analyze_stock(symbol, start_date, end_date, tc_guess_days=30):
    """拡張された株価分析関数"""
    logger = AnalysisLogger()
   
    # 基本分析の実行
    results, data = analyze_stock(symbol, start_date, end_date, tc_guess_days)
   
    if results is not None:
        times, prices = prepare_data(data)
        
        # 各分析の実行
        quality_metrics = validate_fit_quality(times, prices, results, symbol=symbol)
        tc_mean, tc_std, tc_cv, window_consistency = check_stability(times, prices, data=data, symbol=symbol)
        
        # プロット情報の記録を更新
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        plots_info = {
            'main_analysis': f'{symbol}_analysis.png',
            'fit_quality': f'fit_quality_{symbol}_{timestamp}.png',
            'stability': f'stability_{symbol}_{timestamp}.png'
        }
        
        # 結果の保存
        analysis_id = logger.save_analysis_results(
            symbol, results, data, quality_metrics,
            (tc_mean, tc_std, tc_cv, window_consistency),
            start_date, end_date, plots_info
        )
        
        # レポートの生成と表示
        print(logger.generate_report(analysis_id))
        
        return results, data, quality_metrics, (tc_mean, tc_std, tc_cv, window_consistency)
    
    return None, None, None, None

def analyze_markets_from_json(json_file='market_symbols.json', time_windows=[180, 365, 730]):
    """保存された銘柄リストを使用して市場分析を実行"""
    progress_file = 'analysis_progress.json'
    
    # 進捗状況の読み込み
    try:
        with open(progress_file, 'r') as f:
            progress = json.load(f)
    except FileNotFoundError:
        progress = {'completed': [], 'failed': [], 'start_time': None}
    
    # 開始時刻の記録
    if not progress.get('start_time'):
        progress['start_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with open(json_file, 'r') as f:
        markets = json.load(f)
    
    # 全銘柄数の計算
    total_symbols = len(markets['japan']) + len(markets['us']) + \
                   sum(len(symbols) for symbols in markets['indices'].values())
    
    def show_progress(processed_count):
        """進捗状況を表示
        
        Parameters:
        -----------
        processed_count : int
            処理済みの銘柄数
        """
        current_time = datetime.now()
        start_time = datetime.strptime(progress['start_time'], '%Y-%m-%d %H:%M:%S')
        elapsed_time = current_time - start_time
        
        if processed_count > 0:
            avg_time_per_symbol = elapsed_time / processed_count
            remaining_symbols = total_symbols - processed_count
            estimated_remaining_time = avg_time_per_symbol * remaining_symbols
            
            print(f"\n進捗状況:")
            print(f"完了: {len(progress['completed'])} 失敗: {len(progress['failed'])}")
            print(f"進捗率: {processed_count/total_symbols*100:.1f}% ({processed_count}/{total_symbols})")
            print(f"経過時間: {str(elapsed_time).split('.')[0]}")
            print(f"予想残り時間: {str(estimated_remaining_time).split('.')[0]}")

    for category in ['japan', 'us', 'indices']:
        if category == 'indices':
            symbols = [s for region in markets[category].values() for s in region]
        else:
            symbols = markets[category]
        
        print(f"\n=== {category}市場の分析 ===")
        for symbol in symbols:
            if symbol in progress['completed']:
                processed_count += 1
                continue
            
            try:
                analyze_single_market(symbol, time_windows)
                progress['completed'].append(symbol)
            except Exception as e:
                print(f"エラー ({symbol}): {str(e)}")
                progress['failed'].append(symbol)
                
            processed_count += 1
            show_progress(processed_count)
            
            # 進捗の保存
            with open(progress_file, 'w') as f:
                json.dump(progress, f)

def analyze_single_market(symbol, time_windows):
    """単一銘柄の分析"""
    for window in time_windows:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=window)
        
        try:
            print(f"\n分析開始: {symbol} (期間: {window}日)")
            results, data, quality_metrics, stability_metrics = \
                enhanced_analyze_stock(symbol, start_date, end_date)
            
            if results is not None and quality_metrics is not None and data is not None:
                print(f"分析完了: {symbol} (期間: {window}日)")
                
        except Exception as e:
            print(f"エラー ({symbol}, {window}日): {str(e)}")
            continue

if __name__ == "__main__":
    analyze_markets_from_json(json_file='market_symbols_for_test.json')
    
    
