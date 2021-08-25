### This file will be used to conduct data wrangling on the file
### Data_Cortex_Nuclear.txt in order to prepare the data for the
### AutoMLPipe-MC pipeline.

import pandas as pd
import numpy as np

nuclear_cortex_data = pd.read_csv("Data_Cortex_Nuclear.txt")

nuclear_cortex_data.drop(columns=["Genotype", "Treatment", "Behavior"], inplace=True)
print(nuclear_cortex_data.shape)
number = nuclear_cortex_data.count().to_numpy()
print(number)

nuclear_cortex_data.drop(columns=['BAD_N','BCL2_N','H3AcK18_N','EGR1_N','H3MeK4_N'], axis=1, inplace=True)
    
nuclear_cortex_data.rename(columns={"MouseID" : "InstanceID", "class" : "Class"}, inplace=True)

nuclear_cortex_data.replace(['c-CS-m','c-SC-m','c-CS-s','c-SC-s','t-CS-m','t-SC-m','t-CS-s','t-SC-s'], range(0,8), inplace=True)

nuclear_cortex_data.to_csv("Nuclear_Cortex_Data_Wrangled.csv")
