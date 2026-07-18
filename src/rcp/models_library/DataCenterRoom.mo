model DataCenterRoom "Lumped thermal model of a data center room with proportional cooling"
  parameter Real Q_it = 50000 "IT heat load [W]";
  parameter Real C_room = 2.0e6 "Room thermal capacitance [J/K]";
  parameter Real UA = 2000 "Envelope conductance to ambient [W/K]";
  parameter Real T_amb = 30 "Ambient temperature [degC]";
  parameter Real T_set = 24 "Cooling setpoint [degC]";
  parameter Real Q_cool_max = 80000 "Maximum cooling capacity [W]";
  parameter Real k_p = 20000 "Proportional controller gain [W/K]";
  parameter Real COP = 3.5 "Cooling coefficient of performance";
  Real T(start = 27, fixed = true) "Room air temperature [degC]";
  Real Q_cool "Cooling delivered [W]";
  Real P_cool "Cooling electric power [W]";
  Real E_cool(start = 0, fixed = true) "Cumulative cooling energy [J]";
equation
  Q_cool = min(Q_cool_max, max(0.0, k_p * (T - T_set)));
  C_room * der(T) = Q_it + UA * (T_amb - T) - Q_cool;
  P_cool = Q_cool / COP;
  der(E_cool) = P_cool;
end DataCenterRoom;
