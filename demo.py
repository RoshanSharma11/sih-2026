from datetime import date
import matplotlib.pyplot as plt
import meteostat as ms

# Specify location and time range
POINT = ms.Point(28.6139, 77.2090, 113)  # Try with your location
START = date(2024, 1, 1)
END = date(2024, 12, 31)

# Get nearby weather stations
stations = ms.stations.nearby(POINT, limit=4)

# Get daily data & perform interpolation
ts = ms.daily(stations, START, END)
df = ms.interpolate(ts, POINT).fetch()

# Plot line chart including average, minimum and maximum temperature
df.plot(y=[ms.Parameter.TEMP, ms.Parameter.RHUM, ms.Parameter.PRES])
plt.show()