#IMPORT PACKAGES
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import datetime as dt
import pytz #for timezone calculation
import math
import matplotlib.dates as md
import gc
import os
from datetime import datetime
import calendar
import seaborn as sns; sns.set()
import itertools
#import datetime
from time import gmtime, strftime
from matplotlib import cm
from IPython.display import display
#%matplotlib qt
#%matplotlib inline

#SET GLOBAL PARAMETERS
# ================== Global parameters for fonts & sizes =================
FONT_SIZE = 20
rc={'font.size': FONT_SIZE, 'axes.labelsize': FONT_SIZE, 'legend.fontsize': FONT_SIZE, 
    'axes.titlesize': FONT_SIZE, 'xtick.labelsize': FONT_SIZE, 'ytick.labelsize': FONT_SIZE}
plt.rcParams.update(**rc)
plt.rc('font', weight='bold')
 
# For label titles
fontdict={'fontsize': FONT_SIZE, 'fontweight' : 'bold'}
# can add in above dictionary: 'verticalalignment': 'baseline' 

style = 'ggplot' # choose a style from the above options
plt.style.use(style)

def check_polyfit(data_site, ac_cap):
    """Filter the power data, do polyfit estimate, check its quality, and calculate expected energy generated.

    Args:
        data_site (df): Cleaned D-PV time-series data
        ac_cap (int): The maximum real power generated by the pv system due to inverter limitation

    Returns:
        polyfit (polyfit) : function to transform map timestamp into expected power without curtailment
        is_good_polyfit_quality (bool) : True only if more than 50 actual points are near to polyfit result
        energy_generated (float) : calculated energy generated
        energy_generated_expected (float): calculated expected generated energy from the polyfit 
        data_site (df): data_site with expected power column
    """
    data_site.index.rename('ts', inplace = True)

    sunrise, sunset, data_site = filter_sunrise_sunset(data_site)
    data_site['power_relative'] = data_site['power'] / ac_cap
    timestamp_complete = data_site.index
    data_site_more_300 = data_site.loc[data_site['power'] > 300]

    power_array, time_array = filter_power_data_index(data_site_more_300)
    time_array = time_array.strftime('%Y-%m-%d %H:%M:%S')
    time_array = time_array.to_series(index=None, name='None')
    power_array, time_array = filter_data_limited_gradients(power_array, time_array)

    time_array_float = get_datetime_list(time_array)

    polyfit = get_polyfit(time_array_float, power_array, 2)

    polyfit_power_array = polyfit(time_array_float)

    timestamp = timestamp_complete
    timestamp = timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp = get_datetime_list(timestamp)
    data_site['power_expected'] = polyfit(timestamp)
    data_site.loc[data_site['power_expected'] < 0, 'power_expected'] = 0
    
    #correct the power expected when it is below the actual power
    #data_site.loc[data_site['power_expected'] < data_site['power'], 'power_expected'] = data_site['power']
    
    #limit the maximum power expected to be the same with ac capacity of the inverter
    data_site.loc[data_site['power_expected'] > ac_cap, 'power_expected'] = ac_cap

    #plt.plot(data_site.index, data_site['power'])
    #plt.plot(data_site.index, data_site['power_expected'])
    #plt.show()

    error = abs(data_site['power_expected'] - data_site['power'])
    points_near_polyfit_count = error[error<50].count()

    if points_near_polyfit_count > 50: #the initial value is 50
        is_good_polyfit_quality = True
    else:
        is_good_polyfit_quality = False
    
    return data_site, polyfit, is_good_polyfit_quality

def func(a,x):
    """Calculate the result of a quadratic function

    Args:
    a (nd array of dimension 3x1) : a[0] is coefficient of x^2, a[1] is coefficient of x, a[2] is the constant
    x (nd array of dimension nx1) : matrix of x value that will be plugged into the function, n is the number of x values

    Returns:
    y (nd array of dimension nx1) : matrix of result value, n is the number of y values
    """
    y = a[0] * x**2 + a[1] * x + a[2]
    return y

def sum_squared_error(a):
    """Calculate the sum of the square error of the fitting result and the actual value

    Args:
    a (nd array of dimension 3x1) : a[0] is coefficient of x^2, a[1] is coefficient of x, a[2] is the constant
    
    Returns:
    sum_squared_error (float) : a single value of sum squared error. This will be used for the objective value that we
                                want to minimize for the fitting process.
    """
    
    y_fit = func(a,x_for_fitting) #x_for fitting here is a global variable so must be defined before declaring the function.
    sum_squared_error = sum((y_fit - y)**2)
    return sum_squared_error

def check_polyfit_constrained(data, ac_cap):
    """Get the expected generated power, with constrain must be at least the same with the actual power.

    Args:
    data (df) : D-PV time series data with power data
    ac_cap (int): The maximum real power generated by the pv system due to inverter limitation
    
    Returns:
    data (df) : D-PV time series data, filtered sunrise sunset, added with 'power_expected' column and 'power_relative' column
    a (list) : polyfit result in terms of the coefficient of x^2, x, and the constant
    is_good_polyfit_quality (bool) : whether the polyfit quality is good enough or not.
    """
    
    from scipy.optimize import minimize
    from scipy.optimize import NonlinearConstraint
    from scipy.optimize import fmin
    import warnings
    warnings.filterwarnings("ignore", message="delta_grad == 0.0. Check if the approximated function is linear.")
        
    data_site['unix_ts'] = data_site.index.astype(int) / 10**9
    data_site['x_fit'] = (data_site['unix_ts'] - data_site['unix_ts'][0])/60 #this is necessary for the fitting purpose since the precision is broken if we use alarge number.

    data['power_relative'] = data['power'] / ac_cap
    VA_W_RATIO = 1.125
    data['power_limit_vv'] = np.sqrt((VA_W_RATIO*ac_cap)**2 - data['reactive_power']**2)
    sunrise, sunset, data = filter_sunrise_sunset(data)
    
    global POWER_LIMIT_FITTING
    #POWER_LIMIT_FITTING = 3500
    #POWER_LIMIT_FITTING = 500
    #POWER_LIMIT_FITTING = 300
    POWER_LIMIT_FITTING = 1/2*data['power'].max()
    data_for_fitting = data.loc[data['power'] > POWER_LIMIT_FITTING] 
    #this improves the polyfit quality because in the morning the gradient is still increasing, while quadratic model has only
    #decreasing gradient.
    
    global y
    x, y = filter_curtailment(data_for_fitting)
    
    global x_for_fitting
    x_for_fitting = np.array(x)
    y_for_fitting = np.array(y)

    #Set the constraint: the polyfit result - actual power >= 0
    con_func_1 = lambda x: func(a = x, x = x_for_fitting) - y_for_fitting
    lower_bound = NonlinearConstraint(con_func_1, 0, np.inf)

    #Perform the fitting using scipy.optimize.minimize, 'trust-constr' is chosen because we have constrain to add
    res = minimize(sum_squared_error, x0 = [0, 0, 0], method = 'trust-constr', constraints = lower_bound)
    a = res.x #this is the fitting result (quadratic function coefficient)

    data['power_expected'] = func(a, np.array(data['x_fit']))
    
    error = abs(data['power_expected'] - data['power'])
    points_near_polyfit_count = error[error<100].count()

    if points_near_polyfit_count > 50: #the initial value is 50
        is_good_polyfit_quality = True
    else:
        is_good_polyfit_quality = False
    
    #this is for adjusting the power expected in the morning and evening where P < 1000
    data.loc[data['power_expected'] < data['power'], 'power_expected'] = data['power']
    
    #limit the maximum power expected to be the same with ac capacity of the inverter
    data.loc[data['power_expected'] > ac_cap, 'power_expected'] = ac_cap
        
    return data, a, is_good_polyfit_quality 