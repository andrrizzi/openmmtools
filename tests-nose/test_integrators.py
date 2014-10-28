#!/usr/local/bin/env python

#=============================================================================================
# MODULE DOCSTRING
#=============================================================================================

"""
Test custom integrators.

"""

#=============================================================================================
# GLOBAL IMPORTS
#=============================================================================================

import sys
import math
import doctest
import numpy
import time

import simtk.unit as units
import simtk.openmm as openmm
from simtk.openmm import app

from openmmtools import testsystems
from openmmtools import integrators

#=============================================================================================
# CONSTANTS
#=============================================================================================

kB = units.BOLTZMANN_CONSTANT_kB * units.AVOGADRO_CONSTANT_NA

#=============================================================================================
# UTILITY SUBROUTINES
#=============================================================================================

def computeHarmonicOscillatorExpectations(K, mass, temperature):
   """
   Compute mean and variance of potential and kinetic energies for harmonic oscillator.

   Numerical quadrature is used.

   ARGUMENTS

   K - spring constant
   mass - mass of particle
   temperature - temperature

   RETURNS

   values

   """

   values = dict()

   # Compute thermal energy and inverse temperature from specified temperature.
   kB = units.BOLTZMANN_CONSTANT_kB * units.AVOGADRO_CONSTANT_NA
   kT = kB * temperature # thermal energy
   beta = 1.0 / kT # inverse temperature

   # Compute standard deviation along one dimension.
   sigma = 1.0 / units.sqrt(beta * K)

   # Define limits of integration along r.
   r_min = 0.0 * units.nanometers # initial value for integration
   r_max = 10.0 * sigma      # maximum radius to integrate to

   # Compute mean and std dev of potential energy.
   V = lambda r : (K/2.0) * (r*units.nanometers)**2 / units.kilojoules_per_mole # potential in kJ/mol, where r in nm
   q = lambda r : 4.0 * math.pi * r**2 * math.exp(-beta * (K/2.0) * (r*units.nanometers)**2) # q(r), where r in nm
   (IqV2, dIqV2) = scipy.integrate.quad(lambda r : q(r) * V(r)**2, r_min / units.nanometers, r_max / units.nanometers)
   (IqV, dIqV)   = scipy.integrate.quad(lambda r : q(r) * V(r), r_min / units.nanometers, r_max / units.nanometers)
   (Iq, dIq)     = scipy.integrate.quad(lambda r : q(r), r_min / units.nanometers, r_max / units.nanometers)
   values['potential'] = dict()
   values['potential']['mean'] = (IqV / Iq) * units.kilojoules_per_mole
   values['potential']['stddev'] = (IqV2 / Iq) * units.kilojoules_per_mole

   # Compute mean and std dev of kinetic energy.
   values['kinetic'] = dict()
   values['kinetic']['mean'] = (3./2.) * kT
   values['kinetic']['stddev'] = math.sqrt(3./2.) * kT

   return values

def statisticalInefficiency(A_n, B_n=None, fast=False, mintime=3):
  """
  Compute the (cross) statistical inefficiency of (two) timeseries.

  REQUIRED ARGUMENTS
    A_n (numpy array) - A_n[n] is nth value of timeseries A.  Length is deduced from vector.

  OPTIONAL ARGUMENTS
    B_n (numpy array) - B_n[n] is nth value of timeseries B.  Length is deduced from vector.
       If supplied, the cross-correlation of timeseries A and B will be estimated instead of the
       autocorrelation of timeseries A.
    fast (boolean) - if True, will use faster (but less accurate) method to estimate correlation
       time, described in Ref. [1] (default: False)
    mintime (int) - minimum amount of correlation function to compute (default: 3)
       The algorithm terminates after computing the correlation time out to mintime when the
       correlation function furst goes negative.  Note that this time may need to be increased
       if there is a strong initial negative peak in the correlation function.

  RETURNS
    g is the estimated statistical inefficiency (equal to 1 + 2 tau, where tau is the correlation time).
       We enforce g >= 1.0.

  NOTES
    The same timeseries can be used for both A_n and B_n to get the autocorrelation statistical inefficiency.
    The fast method described in Ref [1] is used to compute g.

  REFERENCES
    [1] J. D. Chodera, W. C. Swope, J. W. Pitera, C. Seok, and K. A. Dill. Use of the weighted
    histogram analysis method for the analysis of simulated and parallel tempering simulations.
    JCTC 3(1):26-41, 2007.

  EXAMPLES

  Compute statistical inefficiency of timeseries data with known correlation time.

  >>> import timeseries
  >>> A_n = timeseries.generateCorrelatedTimeseries(N=100000, tau=5.0)
  >>> g = statisticalInefficiency(A_n, fast=True)

  """

  # Create numpy copies of input arguments.
  A_n = numpy.array(A_n)
  if B_n is not None:
    B_n = numpy.array(B_n)
  else:
    B_n = numpy.array(A_n)

  # Get the length of the timeseries.
  N = A_n.size

  # Be sure A_n and B_n have the same dimensions.
  if(A_n.shape != B_n.shape):
    raise ParameterError('A_n and B_n must have same dimensions.')

  # Initialize statistical inefficiency estimate with uncorrelated value.
  g = 1.0

  # Compute mean of each timeseries.
  mu_A = A_n.mean()
  mu_B = B_n.mean()

  # Make temporary copies of fluctuation from mean.
  dA_n = A_n.astype(numpy.float64) - mu_A
  dB_n = B_n.astype(numpy.float64) - mu_B

  # Compute estimator of covariance of (A,B) using estimator that will ensure C(0) = 1.
  sigma2_AB = (dA_n * dB_n).mean() # standard estimator to ensure C(0) = 1

  # Trap the case where this covariance is zero, and we cannot proceed.
  if(sigma2_AB == 0):
    raise ParameterException('Sample covariance sigma_AB^2 = 0 -- cannot compute statistical inefficiency')

  # Accumulate the integrated correlation time by computing the normalized correlation time at
  # increasing values of t.  Stop accumulating if the correlation function goes negative, since
  # this is unlikely to occur unless the correlation function has decayed to the point where it
  # is dominated by noise and indistinguishable from zero.
  t = 1
  increment = 1
  while (t < N-1):

    # compute normalized fluctuation correlation function at time t
    C = sum( dA_n[0:(N-t)]*dB_n[t:N] + dB_n[0:(N-t)]*dA_n[t:N] ) / (2.0 * float(N-t) * sigma2_AB)

    # Terminate if the correlation function has crossed zero and we've computed the correlation
    # function at least out to 'mintime'.
    if (C <= 0.0) and (t > mintime):
      break

    # Accumulate contribution to the statistical inefficiency.
    g += 2.0 * C * (1.0 - float(t)/float(N)) * float(increment)

    # Increment t and the amount by which we increment t.
    t += increment

    # Increase the interval if "fast mode" is on.
    if fast: increment += 1

  # g must be at least unity
  if (g < 1.0): g = 1.0

  # Return the computed statistical inefficiency.
  return g

def check_stability(integrator, test, platform=None, nsteps=100, temperature=300.0*unit.kelvin):
   """
   Check that the simulation does not explode over a number integration steps.

   Parameters
   ----------
   integrator : simtk.openmm.Integrator
      The integrator to test.
   test : testsystem
      The testsystem to test.

   """
   kT = kB * temperature

   # Create Context and initialize positions.
   if platform:
      context = openmm.Context(system, integrator, platform)
   else:
      context = openmm.Context(system, integrator)
   context.setPositions(positions)
   context.setVelocitiesToTemperature(temperature) # TODO: Make deterministic.

   # Take a number of steps.
   integrator.step(nsteps)

   # Check that simulation has not exploded.
   state = context.getState(getEnergy=True)
   potential = state.getPotentialEnergy() / kT
   if numpy.isnan(potential):
      raise Exception("Potential energy became NaN.")

   del context

   return

#=============================================================================================
# TESTS
#=============================================================================================

def test_dummy_integrator():
   """
   Test DummyIntegrator for stability over a short number of steps of a harmonic oscillator.

   """
   from openmmtools import integrators, testsystems
   integrator = integrators.DummyIntegrator()
   test = testsystems.HarmonicOscillator()
   check_stability(integrator, test)

def test_gradient_descent():
   """
   Test GradientDescentMinimizationIntegrator for stability over a short number of steps of a harmonic oscillator.

   """
   from openmmtools import integrators, testsystems
   integrator = integrators.GradientDescentMinimizationIntegrator()
   test = testsystems.HarmonicOscillator()
   check_stability(integrator, test)


