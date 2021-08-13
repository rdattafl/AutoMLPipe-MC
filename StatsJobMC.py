import sys
import time
import pandas as pd
import glob
import numpy as np
from scipy import interp,stats
import matplotlib.pyplot as plt
from matplotlib import rc
import os
from sklearn.metrics import auc
import csv
from statistics import mean,stdev
import pickle
import copy

def job(full_path,encoded_algos,plot_FI_box,class_label,instance_label,cv_partitions,plot_metric_boxplots,primary_metric,top_results,sig_cutoff,jupyterRun):
    job_start_time = time.time()
    data_name = full_path.split('/')[-1]
    print(full_path)

    #Translate metric from scikitlearn standard (currently balanced accuracy is hardcoded for use in FI plots due to no-skill normalization)
    metric_term_dict = {'balanced_accuracy': 'Balanced Accuracy','confusion_matrix': 'Confusion Matrix', 'roc_auc': 'ROC_AUC','matthews_corrcoef': 'Matthews Correlation Coefficient', 'plot_confusion_matrix': 'Confusion Matrix Plot'}
    primary_metric = metric_term_dict[primary_metric]

    algorithms,abbrev,colors,original_headers = preparation(full_path,encoded_algos)

    result_table,metric_dict = primaryStats(algorithms,original_headers,cv_partitions,full_path,data_name,instance_label,class_label,abbrev,colors,jupyterRun)

    doPlotMeanAUC(result_table, abbrev, colors, full_path, jupyterRun)
    
    # doPlotROC(result_table,colors,full_path,jupyterRun)

    metrics = list(metric_dict[algorithms[0]].keys()) #metric names

    saveMetricMeans(full_path,metrics,metric_dict)
    saveMetricStd(full_path,metrics,metric_dict)

    if eval(plot_metric_boxplots):
        metricBoxplots(full_path,metrics,algorithms,metric_dict,jupyterRun)

    #Save Kruskal Wallis and Mann Whitney Stats
    if len(algorithms) > 1:
        kruskal_summary = kruskalWallis(full_path,metrics,algorithms,metric_dict,sig_cutoff)
        wilcoxonRank(full_path,metrics,algorithms,metric_dict,kruskal_summary,sig_cutoff)
        mannWhitneyU(full_path,metrics,algorithms,metric_dict,kruskal_summary,sig_cutoff)

    #Visualize FI - Currently set up to only use Balanced Accuracy for composite FI plot visualization
    #Prepare for feature importance visualizations
    fi_df_list,fi_ave_list,fi_ave_norm_list,ave_metric_list,all_feature_list,non_zero_union_features,non_zero_union_indexes = prepFI(algorithms,full_path,abbrev,metric_dict,'Balanced Accuracy',top_results)

    #Select 'top' feature for vizualization
    featuresToViz = selectForViz(top_results,non_zero_union_features,non_zero_union_indexes,algorithms,ave_metric_list,fi_ave_norm_list)

    if eval(plot_FI_box):
        #Generate FI boxplots for each modeling algorithm
        doFIBoxplots(full_path,fi_df_list,algorithms,original_headers,jupyterRun)

    #Normalize FI scores for normalized composite FI plot
    top_fi_ave_norm_list,all_feature_listToViz = normalizeFI(featuresToViz,all_feature_list,algorithms,fi_ave_norm_list)

    #Generate Normalized composite FI plot
    composite_FI_plot(top_fi_ave_norm_list, algorithms, list(colors.values()), all_feature_listToViz, 'Norm',full_path,jupyterRun, 'Normalized Feature Importance')

    #Fractionate FI scores for normalized and fractionated composite FI plot
    fracLists = fracFI(top_fi_ave_norm_list)

    #Generate Normalized and Fractioned composite FI plot
    composite_FI_plot(fracLists, algorithms, list(colors.values()), all_feature_listToViz, 'Norm_Frac',full_path,jupyterRun, 'Normalized and Fractioned Feature Importance')

    #Weight FI scores for normalized and (model performance) weighted composite FI plot
    weightedLists,weights = weightFI(ave_metric_list,top_fi_ave_norm_list)

    #Generate Normalized and Weighted Compount FI plot
    composite_FI_plot(weightedLists, algorithms, list(colors.values()), all_feature_listToViz, 'Norm_Weight',full_path,jupyterRun, 'Normalized and Weighted Feature Importance')

    #Weight the Fractionated FI scores for normalized,fractionated, and weighted compount FI plot
    weightedFracLists = weighFracFI(fracLists,weights)

    #Generate Normalized, Fractionated, and Weighted Compount FI plot
    composite_FI_plot(weightedFracLists, algorithms, list(colors.values()), all_feature_listToViz, 'Norm_Frac_Weight',full_path,jupyterRun, 'Normalized, Fractioned, and Weighted Feature Importance')

    saveRuntime(full_path,job_start_time)
    parseRuntime(full_path,abbrev)

    # Print completion
    print(data_name + " phase 5 complete")
    experiment_path = '/'.join(full_path.split('/')[:-1])
    job_file = open(experiment_path + '/jobsCompleted/job_stats_' + data_name + '.txt', 'w')
    job_file.write('complete')
    job_file.close()

def preparation(full_path,encoded_algos):
    #Create Directory
    if not os.path.exists(full_path+'/training/results'):
        os.mkdir(full_path+'/training/results')
    #Decode algos
    algorithms = []
    possible_algos = ['Naive Bayes','Decision Tree','Random Forest','XGB','SVM','ANN','K Neighbors']
    algorithms = decode(algorithms, encoded_algos, possible_algos, 0)
    algorithms = decode(algorithms, encoded_algos, possible_algos, 1)
    algorithms = decode(algorithms, encoded_algos, possible_algos, 2)
    algorithms = decode(algorithms, encoded_algos, possible_algos, 3)
    algorithms = decode(algorithms, encoded_algos, possible_algos, 4)
    algorithms = decode(algorithms, encoded_algos, possible_algos, 5)
    algorithms = decode(algorithms, encoded_algos, possible_algos, 6)
    abbrev = {'Naive Bayes':'NB','Decision Tree':'DT','Random Forest':'RF','XGB':'XGB','SVM':'SVM','ANN':'ANN','K Neighbors':'KN'}
    colors = {'Naive Bayes':'grey','Decision Tree':'yellow','Random Forest':'orange','XGB':'purple','SVM':'blue','ANN':'red','K Neighbors':'seagreen'}
    #Get Original Headers
    original_headers = pd.read_csv(full_path+"/exploratory/OriginalHeaders.csv",sep=',').columns.values.tolist()
    return algorithms,abbrev,colors,original_headers

def primaryStats(algorithms,original_headers,cv_partitions,full_path,data_name,instance_label,class_label,abbrev,colors,jupyterRun):
    #Main Ops
    result_table = []
    metric_dict = {}
    for algorithm in algorithms:
        alg_result_table = []
        # Define evaluation stats variable lists
        s_bac = []
        s_aap = []
        s_ras = []
        s_mcc = []

        # Define feature importance lists
        FI_all = []
        FI_ave = [0] * len(original_headers)  # Holds only the selected feature FI results for each partition

        # Define AUC list to calculate mean AUC value for each algorithm
        aucs = []

        #Gather statistics over all CV partitions
        for cvCount in range(0,cv_partitions):
            result_file = full_path+'/training/'+abbrev[algorithm]+"_CV_"+str(cvCount)+"_metrics"
            file = open(result_file, 'rb')
            results = pickle.load(file)
            file.close()

            bac = results[0]
            conf = results[1]
            roc_auc = results[2]
            mcc = results[3]
            conf_plot = results[4]
            fi = results[5]

            # Determine the total number of labeled instances
            num_labeled = 0
            for classNum in range(0, len(conf)):
                num_labeled += conf[classNum][0];

            # Calculate the aggregate average precision across all classes
            agg_avg_prec = 0
            for classNum in range(0,len(conf)):
                agg_avg_prec += (conf[classNum][classNum])/num_labeled

            agg_avg_prec = agg_avg_prec / len(conf);
                
            # Store values for later use in result_dict
            s_bac.append(bac)
            s_aap.append(agg_avg_prec)
            s_ras.append(roc_auc)
            s_mcc.append(mcc)

            alg_result_table.append([bac, agg_avg_prec, roc_auc, mcc, fi])

            # Update ROC plot variable lists
            # tprs.append(interp(mean_fpr, fpr, tpr))
            # tprs[-1][0] = 0.0
            aucs.append(roc_auc)

            # Format feature importance scores as list (takes into account that all features are not in each CV partition)
            tempList = []
            j = 0
            headers = pd.read_csv(full_path+'/CVDatasets/'+data_name+'_CV_'+str(cvCount)+'_Test.csv').columns.values.tolist()
            if instance_label != 'None':
                headers.remove(instance_label)
            headers.remove(class_label)
            for each in original_headers:
                if each in headers:  # Check if current feature from original dataset was in the partition
                    # Deal with features not being in original order (find index of current feature list.index())
                    f_index = headers.index(each)
                    FI_ave[j] += fi[f_index]
                    tempList.append(fi[f_index])
                else:
                    tempList.append(0)
                j += 1

            FI_all.append(tempList)

            # Save Confusion Matrix plot as a figure for reference
            conf_plot.plot()
            plt.savefig(full_path+'/training/results/'+abbrev[algorithm]+"_CV_"+str(cvCount)+'_ConfusionMatrixPlot.png', bbox_inches = 'tight')
            if eval(jupyterRun):
                plt.show()
            else:
                plt.close('all')

        #Save Average Algorithm Stats
        results = {'Balanced Accuracy': s_bac,'Aggregate Average Precision': s_aap, 'ROC_AUC': s_ras, 'Matthews Correlation Coefficient': s_mcc}
        dr = pd.DataFrame(results)
        filepath = full_path+'/training/results/'+abbrev[algorithm]+"_performance.csv"
        dr.to_csv(filepath, header=True, index=False)
        metric_dict[algorithm] = results

        #Turn FI sums into averages
        for i in range(0, len(FI_ave)):
            FI_ave[i] = FI_ave[i] / float(cv_partitions)

        #Save Average FI Stats
        save_FI(FI_all, abbrev[algorithm], original_headers, full_path)

        #Store Mean AUC metric for creating global AUC bar plot later
        mean_auc = np.mean(aucs)
        result_dict = {'algorithm' : algorithm, 'auc' : mean_auc}
        result_table.append(result_dict)

    result_table = pd.DataFrame.from_dict(result_table)
    result_table.set_index('algorithm',inplace=True)

    return result_table,metric_dict

def doPlotMeanAUC(result_table,abbrev, colors, full_path, jupyterRun):
    a = abbrev.values()
    c = colors.values()
    ax = plt.bar(range(0,len(result_table)), result_table['auc'],color=c)
    plt.xlabel('Algorithm')
    plt.ylabel('Mean AUC')
    plt.title('Mean AUC Across All ML Algorithms')
    plt.xticks(np.arange(0.0, len(result_table), 1.0), a)
    plt.savefig(full_path+'/training/results/Summary_MeanAUC.png', bbox_inches="tight")
    if eval(jupyterRun):
        plt.show()
    else:
        plt.close('all')    


##def doPlotROC(result_table,colors,full_path,jupyterRun):
##    #Plot summarizing average ROC across algorithms
##    count = 0
##    for i in result_table.index:
##        plt.plot(result_table.loc[i]['fpr'],result_table.loc[i]['tpr'], color=colors[i],label="{}, AUC={:.3f}".format(i, result_table.loc[i]['auc']))
##        count += 1
##    plt.rcParams["figure.figsize"] = (6,6)
##    plt.plot([0, 1], [0, 1], color='orange', linestyle='--', label='No-Skill', alpha=.8)
##    plt.xticks(np.arange(0.0, 1.1, step=0.1))
##    plt.xlabel("False Positive Rate", fontsize=15)
##    plt.yticks(np.arange(0.0, 1.1, step=0.1))
##    plt.ylabel("True Positive Rate", fontsize=15)
##    #plt.title('Comparing Algorithms: Testing Data with CV', fontweight='bold', fontsize=15)
##    plt.legend(loc="upper left", bbox_to_anchor=(1.01,1))
##    #plt.legend(prop={'size': 13}, loc='best')
##    plt.savefig(full_path+'/training/results/Summary_ROC.png', bbox_inches="tight")
##    if eval(jupyterRun):
##        plt.show()
##    else:
##        plt.close('all')

def saveMetricMeans(full_path,metrics,metric_dict):
    #Save Average Metrics (mean)
    with open(full_path+'/training/results/Summary_performance_mean.csv',mode='w', newline="") as file:
        writer = csv.writer(file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        e = ['']
        e.extend(metrics)
        writer.writerow(e) #Write headers (balanced accuracy, etc.)
        for algorithm in metric_dict:
            astats = []
            for l in list(metric_dict[algorithm].values()):
                l = [float(i) for i in l]
                meani = mean(l)
                astats.append(str(meani))
            toAdd = [algorithm]
            toAdd.extend(astats)
            writer.writerow(toAdd)
    file.close()

def saveMetricStd(full_path,metrics,metric_dict):
    # Save Average Metrics (std)
    with open(full_path + '/training/results/Summary_performance_std.csv', mode='w', newline="") as file:
        writer = csv.writer(file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        e = ['']
        e.extend(metrics)
        writer.writerow(e)  # Write headers (balanced accuracy, etc.)
        for algorithm in metric_dict:
            astats = []
            for l in list(metric_dict[algorithm].values()):
                l = [float(i) for i in l]
                std = stdev(l)
                astats.append(str(std))
            toAdd = [algorithm]
            toAdd.extend(astats)
            writer.writerow(toAdd)
    file.close()

def metricBoxplots(full_path,metrics,algorithms,metric_dict,jupyterRun):
    #Save boxplots for each metrics
    if not os.path.exists(full_path + '/training/results/performanceBoxplots'):
        os.mkdir(full_path + '/training/results/performanceBoxplots')
    for metric in metrics:
        tempList = []
        for algorithm in algorithms:
            tempList.append(metric_dict[algorithm][metric])

        td = pd.DataFrame(tempList)
        td = td.transpose()
        td.columns = algorithms

        boxplot = td.boxplot(column=algorithms,rot=90) #, rot=45
        #plt.title('Comparing Algorithm ' + str(metric))
        plt.ylabel(str(metric))
        plt.xlabel('ML Algorithm')
        plt.savefig(full_path + '/training/results/performanceBoxplots/Compare_'+metric+'.png', bbox_inches="tight")
        if eval(jupyterRun):
            plt.show()
        else:
            plt.close('all')

def kruskalWallis(full_path,metrics,algorithms,metric_dict,sig_cutoff):
    if not os.path.exists(full_path + '/training/results/KWMW'):
        os.mkdir(full_path + '/training/results/KWMW')
    label = ['Statistic', 'P-Value', 'Sig(*)']
    kruskal_summary = pd.DataFrame(index=metrics, columns=label)
    for metric in metrics:
        tempArray = []
        for algorithm in algorithms:
            tempArray.append(metric_dict[algorithm][metric])
        try:
            result = stats.kruskal(*tempArray)
        except:
            result = [tempArray[0],1]
        kruskal_summary.at[metric, 'Statistic'] = str(round(result[0], 6))
        kruskal_summary.at[metric, 'P-Value'] = str(round(result[1], 6))
        if result[1] < sig_cutoff:
            kruskal_summary.at[metric, 'Sig(*)'] = str('*')
        else:
            kruskal_summary.at[metric, 'Sig(*)'] = str('')
    kruskal_summary.to_csv(full_path + '/training/results/KWMW/KruskalWallis.csv')
    return kruskal_summary

def wilcoxonRank(full_path,metrics,algorithms,metric_dict,kruskal_summary,sig_cutoff):
    """ Apply non-parametric Wilcoxon signed-rank test (pairwise comparisons). If a significant Kruskal Wallis algorithm difference was found for a given metric, Wilcoxon tests individual algorithm pairs
    to determine if there is a statistically significant difference in algorithm performance across CV runs. Test statistic will be zero if all scores from one set are
    larger than the other."""
    for metric in metrics:
        if kruskal_summary['Sig(*)'][metric] == '*':
            wilcoxon_stats = []
            done = []
            for algorithm1 in algorithms:
                for algorithm2 in algorithms:
                    if not [algorithm1,algorithm2] in done and not [algorithm2,algorithm1] in done and algorithm1 != algorithm2:
                        set1 = metric_dict[algorithm1][metric]
                        set2 = metric_dict[algorithm2][metric]
                        #handle error when metric values are equal for both algorithms
                        combined = copy.deepcopy(set1)
                        combined.extend(set2)
                        if all(x==combined[0] for x in combined): #Check if all nums are equal in sets
                            report = ['NA',1]
                        else: # Apply Wilcoxon Rank Sum test
                            report = stats.wilcoxon(set1,set2,zero_method='zsplit')
                        #Summarize test information in list
                        tempstats = [algorithm1,algorithm2,report[0],report[1],'']
                        if report[1] < sig_cutoff:
                            tempstats[4] = '*'
                        wilcoxon_stats.append(tempstats)
                        done.append([algorithm1,algorithm2])
            #Export test results
            wilcoxon_stats_df = pd.DataFrame(wilcoxon_stats)
            wilcoxon_stats_df.columns = ['Algorithm 1', 'Algorithm 2', 'Statistic', 'P-Value', 'Sig(*)']
            wilcoxon_stats_df.to_csv(full_path + '/training/results/KWMW/WilcoxonRank_'+metric+'.csv', index=False)

def mannWhitneyU(full_path,metrics,algorithms,metric_dict,kruskal_summary,sig_cutoff):
    for metric in metrics:
        if kruskal_summary['Sig(*)'][metric] == '*':
            mann_stats = []
            done = []
            for algorithm1 in algorithms:
                for algorithm2 in algorithms:
                    if not [algorithm1,algorithm2] in done and not [algorithm2,algorithm1] in done and algorithm1 != algorithm2:
                        set1 = metric_dict[algorithm1][metric]
                        set2 = metric_dict[algorithm2][metric]
                        combined = copy.deepcopy(set1)
                        combined.extend(set2)
                        if all(x==combined[0] for x in combined): #Check if all nums are equal in sets
                            report = [combined[0],1]
                        else:
                            report = stats.mannwhitneyu(set1,set2)
                        tempstats = [algorithm1,algorithm2,report[0],report[1],'']
                        if report[1] < sig_cutoff:
                            tempstats[4] = '*'
                        mann_stats.append(tempstats)
                        done.append([algorithm1,algorithm2])
            mann_stats_df = pd.DataFrame(mann_stats)
            mann_stats_df.columns = ['Algorithm 1', 'Algorithm 2', 'Statistic', 'P-Value', 'Sig(*)']
            mann_stats_df.to_csv(full_path + '/training/results/KWMW/MannWhitneyU.csv', index=False)

def prepFI(algorithms,full_path,abbrev,metric_dict,primary_metric,top_results):
    fi_df_list = []         # algorithm feature importance dataframe list (used to generate FI boxplots for each algorithm)
    fi_ave_list = []        # algorithm feature importance averages list (used to generate composite FI barplots)
    ave_metric_list = []    # algorithm focus metric averages list (used in weighted FI viz)
    all_feature_list = []   # list of pre-feature selection feature names as they appear in FI reports for each algorithm

    for algorithm in algorithms:
        # Get relevant feature importance info
        temp_df = pd.read_csv(full_path+'/training/results/FI/'+abbrev[algorithm]+"_FI.csv") #CV FI scores for all original features in dataset.
        if algorithm == algorithms[0]:  # Should be same for all algorithm files (i.e. all original features in standard CV dataset order)
            all_feature_list = temp_df.columns.tolist()
        fi_df_list.append(temp_df)
        fi_ave_list.append(temp_df.mean().tolist()) #Saves average FI scores over CV runs

        # Get relevant metric info
        avgBA = mean(metric_dict[algorithm][primary_metric])
        ave_metric_list.append(avgBA)

    #Normalize Average Scores (0 - 1)
    fi_ave_norm_list = []
    for each in fi_ave_list:  # each algorithm
        normList = []
        for i in range(len(each)):
            if each[i] <= 0: #Feature importance scores assumed to be uninformative if at or below 0
                normList.append(0)
            else:
                normList.append((each[i]) / (max(each)))
        fi_ave_norm_list.append(normList)

    #Identify features with non-zero averages
    alg_non_zero_FI_list = [] #stores list of feature name lists that are non-zero for each algorithm
    for each in fi_ave_list:  # each algorithm
        temp_non_zero_list = []
        for i in range(len(each)):  # each feature
            if each[i] > 0.0:
                temp_non_zero_list.append(all_feature_list[i]) #add feature names with positive values (doesn't need to be normalized for this)
        alg_non_zero_FI_list.append(temp_non_zero_list)

    non_zero_union_features = alg_non_zero_FI_list[0]  # grab first algorithm's list

    #Identify union of features with non-zero averages over all algorithms (i.e. if any algorithm found a non-zero score it will be considered for inclusion in top feature visualizations)
    for j in range(1, len(algorithms)):
        non_zero_union_features = list(set(non_zero_union_features) | set(alg_non_zero_FI_list[j]))
    non_zero_union_indexes = []
    for i in non_zero_union_features:
        non_zero_union_indexes.append(all_feature_list.index(i))

    return fi_df_list,fi_ave_list,fi_ave_norm_list,ave_metric_list,all_feature_list,non_zero_union_features,non_zero_union_indexes

def selectForViz(top_results,non_zero_union_features,non_zero_union_indexes,algorithms,ave_metric_list,fi_ave_norm_list):
    #Identify list of top features over all algorithms to visualize (note that best features to vizualize are chosen using algorithm performanc weighting and normalization: frac plays no useful role here only for viz)
    featuresToViz = None
    if len(non_zero_union_features) > top_results: #Keep all features if there are fewer than specified top results
        # Identify a top set of feature values
        scoreSumDict = {}
        i = 0
        for each in non_zero_union_features:  # for each non-zero feature
            for j in range(len(algorithms)):  # for each algorithm
                # grab target score from each algorithm
                score = fi_ave_norm_list[j][non_zero_union_indexes[i]]
                # multiply score by algorithm performance weight
                weight = ave_metric_list[j]
                if weight <= .5:
                    weight = 0
                if not weight == 0:
                    weight = (weight - 0.5) / 0.5
                score = score * weight
                if not each in scoreSumDict:
                    scoreSumDict[each] = score
                else:
                    scoreSumDict[each] += score
            i += 1

        for each in scoreSumDict:
            scoreSumDict[each] = scoreSumDict[each] / len(algorithms)

        # Sort features by decreasing score
        scoreSumDict_features = sorted(scoreSumDict, key=lambda x: scoreSumDict[x], reverse=True)

        featuresToViz = scoreSumDict_features[0:top_results]
    else:
        featuresToViz = non_zero_union_features  # Ranked feature name order
    return featuresToViz

def doFIBoxplots(full_path,fi_df_list,algorithms,original_headers,jupyterRun):
    #Generate individual feature importance boxplots for each algorithm
    counter = 0
    for df in fi_df_list:
        fig = plt.figure(figsize=(15, 4))
        boxplot = df.boxplot(rot=90)
        plt.title(algorithms[counter])
        plt.ylabel('Feature Importance Score')
        plt.xlabel('Features')
        plt.xticks(np.arange(1, len(original_headers) + 1), original_headers, rotation='vertical')
        plt.savefig(full_path+'/training/results/FI/' + algorithms[counter] + '_boxplot',bbox_inches="tight")
        if eval(jupyterRun):
            plt.show()
        else:
            plt.close('all')
        counter += 1

def normalizeFI(featuresToViz,all_feature_list,algorithms,fi_ave_norm_list):
    #Create Normalized dataframes with feature viz subsets (normalization itself was already completed in prepFI)
    feature_indexToViz = []
    for i in featuresToViz:
        feature_indexToViz.append(all_feature_list.index(i))

    # Preserve features in original dataset order for consistency
    top_fi_ave_norm_list = []
    for i in range(len(algorithms)):
        tempList = []
        for j in range(len(fi_ave_norm_list[i])):
            if j in feature_indexToViz:
                tempList.append(fi_ave_norm_list[i][j])
        top_fi_ave_norm_list.append(tempList)

    # Create feature name list in propper order
    all_feature_listToViz = []
    for j in (all_feature_list):
        if j in featuresToViz:
            all_feature_listToViz.append(j)

    return top_fi_ave_norm_list,all_feature_listToViz

def fracFI(top_fi_ave_norm_list):
    #Transforms feature scores so that they sum to 1 over all features.  This way Norm_Frac plot, there is equal total bar area for each algorithm.
    fracLists = []
    for each in top_fi_ave_norm_list: #each algorithm
        fracList = []
        for i in range(len(each)): #each feature
            if sum(each) == 0: #check that all feature scores are not zero to avoid zero division error
                fracList.append(0)
            else:
                fracList.append((each[i] / (sum(each))))
        fracLists.append(fracList)
    return fracLists

def weightFI(ave_metric_list,top_fi_ave_norm_list):
    #Weights the feature importance scores by algorithm performance (intuitive because when interpreting featuer importances we want to place more weight on better performing algorithms)
    # Prepare weights
    weights = []
    # replace all balanced accuraces <=.5 with 0
    for i in range(len(ave_metric_list)):
        if ave_metric_list[i] <= .5:
            ave_metric_list[i] = 0

    # normalize balanced accuracies
    for i in range(len(ave_metric_list)):
        if ave_metric_list[i] == 0:
            weights.append(0)
        else:
            weights.append((ave_metric_list[i] - 0.5) / 0.5)

    # Weight normalized feature importances
    weightedLists = []
    for i in range(len(top_fi_ave_norm_list)):
        weightList = np.multiply(weights[i], top_fi_ave_norm_list[i]).tolist()
        weightedLists.append(weightList)

    return weightedLists,weights

def weighFracFI(fracLists,weights):
    # Weight normalized and fractionated feature importances (This combination gives the most intutive visualization for comparing and contrasting FI across all algorithms)
    weightedFracLists = []

    for i in range(len(fracLists)):
        weightList = np.multiply(weights[i], fracLists[i]).tolist()
        weightedFracLists.append(weightList)
    return weightedFracLists

def saveRuntime(full_path,job_start_time):
    # Save Runtime
    runtime_file = open(full_path + '/runtime/runtime_Stats.txt', 'w')
    runtime_file.write(str(time.time() - job_start_time))
    runtime_file.close()

def parseRuntime(full_path,abbrev):
    # Parse Runtime
    dict = {}
    for file_path in glob.glob(full_path+'/runtime/*.txt'):
        f = open(file_path,'r')
        val = float(f.readline())
        ref = file_path.split('/')[-1].split('_')[1].split('.')[0]
        if ref in abbrev:
            ref = abbrev[ref]
        if not ref in dict:
            dict[ref] = val
        else:
            dict[ref] += val

    with open(full_path+'/runtimes.csv',mode='w', newline="") as file:
        writer = csv.writer(file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["Pipeline Component","Time (sec)"])
        writer.writerow(["Exploratory Analysis",dict['exploratory']])
        writer.writerow(["Preprocessing",dict['preprocessing']])
        try:
            writer.writerow(["Mutual Information",dict['mutualinformation']])
        except:
            pass
        try:
            writer.writerow(["MultiSURF",dict['multisurf']])
        except:
            pass
        writer.writerow(["Feature Selection",dict['featureselection']])
        try:
            writer.writerow(["Naive Bayes",dict['NB']])
        except:
            pass
        try:
            writer.writerow(["Decision Tree",dict['DT']])
        except:
            pass
        try:
            writer.writerow(["Random Forest",dict['RF']])
        except:
            pass
        try:
            writer.writerow(["XGB",dict['XGB']])
        except:
            pass
        try:
            writer.writerow(["Support Vector Machine",dict['SVM']])
        except:
            pass
        try:
            writer.writerow(["Artificial Neural Network",dict['ANN']])
        except:
            pass
        try:
            writer.writerow(["K Nearest Neighbors",dict['KN']])
        except:
            pass
        try:
            writer.writerow(["eLCS",dict['eLCS']])
        except:
            pass
        try:
            writer.writerow(["XCS",dict['XCS']])
        except:
            pass
        try:
            writer.writerow(["ExSTraCS",dict['ExSTraCS']])
        except:
            pass
        writer.writerow(["Stats Summary",dict['Stats']])
        #for key,value in dict.items():
        #    writer.writerow([key,value])

def save_FI(FI_all,algorithm,globalFeatureList,full_path):
    dr = pd.DataFrame(FI_all)
    if not os.path.exists(full_path+'/training/results/FI/'):
        os.mkdir(full_path+'/training/results/FI/')
    filepath = full_path+'/training/results/FI/'+algorithm+"_FI.csv"
    dr.to_csv(filepath, header=globalFeatureList, index=False)

def decode(algorithms,encoded_algos,possible_algos,index):
    if encoded_algos[index] == "1":
        algorithms.append(possible_algos[index])
    return algorithms


def composite_FI_plot(fi_list, algorithms, algColors, all_feature_listToViz, figName,full_path,jupyterRun,yLabelText):
    # y-axis in bold
    rc('font', weight='bold', size=16)

    # The position of the bars on the x-axis
    r = all_feature_listToViz
    barWidth = 0.75
    plt.figure(figsize=(24, 12))

    p1 = plt.bar(r, fi_list[0], color=algColors[0], edgecolor='white', width=barWidth)

    bottoms = []
    for i in range(len(algorithms) - 1):
        for j in range(i + 1):
            if j == 0:
                bottom = np.array(fi_list[0])
            else:
                bottom += np.array(fi_list[j])
        bottoms.append(bottom)

    if not isinstance(bottoms, list):
        bottoms = bottoms.tolist()

    ps = [p1[0]]
    for i in range(len(algorithms) - 1):
        p = plt.bar(r, fi_list[i + 1], bottom=bottoms[i], color=algColors[i + 1], edgecolor='white', width=barWidth)
        ps.append(p[0])

    lines = tuple(ps)

    # Custom X axis
    plt.xticks(np.arange(len(all_feature_listToViz)), all_feature_listToViz, rotation='vertical')
    plt.xlabel("Feature", fontsize=20)
    plt.ylabel(yLabelText, fontsize=20)
    #plt.legend(lines, algorithms, loc=0, fontsize=16)
    plt.legend(lines[::-1], algorithms[::-1],loc="upper left", bbox_to_anchor=(1.01,1))
    plt.savefig(full_path+'/training/results/FI/Compare_FI_' + figName + '.png', bbox_inches='tight')
    if eval(jupyterRun):
        plt.show()
    else:
        plt.close('all')

if __name__ == '__main__':
    job(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5],int(sys.argv[6]),sys.argv[7],sys.argv[8],int(sys.argv[9]),float(sys.argv[10]),sys.argv[11])