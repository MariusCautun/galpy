# Superclass for spherical distribution functions, contains
#   - sphericaldf: superclass of all spherical DFs
#   - isotropicsphericaldf: superclass of all isotropic spherical DFs
#   - anisotropicsphericaldf: superclass of all anisotropic spherical DFs
import numpy
import scipy.interpolate
from .df import df
from ..potential import evaluatePotentials, vesc
from ..potential.SCFPotential import _xiToR
from ..orbit import Orbit
from ..util import conversion
from ..util.conversion import physical_conversion

class sphericaldf(df):
    """Superclass for spherical distribution functions"""
    def __init__(self,ro=None,vo=None):
        """
        NAME:

            __init__

        PURPOSE:

            Initializes a spherical DF

        INPUT:

           ro= ,vo= galpy unit parameters

        OUTPUT:

            None

        HISTORY:

            2020-07-22 - Written - Lane (UofT)

        """
        df.__init__(self,ro=ro,vo=vo)

############################## EVALUATING THE DF###############################
    @physical_conversion('phasespacedensity',pop=True)
    def __call__(self,*args,**kwargs):
        """
        NAME:

            __call__

        PURPOSE:

            return the DF

        INPUT:

            Either:

                a) (E,L,Lz): tuple of E and (optionally) L and (optionally) Lz.
                    Each may be Quantity
                    
                b) R,vR,vT,z,vz,phi: 

                c) Orbit instance: orbit.Orbit instance and if specific time 
                    then orbit.Orbit(t) 

        OUTPUT:

            Value of DF

        HISTORY:

            2020-07-22 - Written - Lane (UofT)

        """
        # Stub for calling the DF as a function of either a) R,vR,vT,z,vz,phi,
        # b) Orbit, c) E,L (Lz?) --> maybe depends on the actual form?
        
        # Get E,L,Lz. Generic requirements for any possible spherical DF?
        if len(args) == 1:
            if not isinstance(args[0],Orbit): # Assume tuple (E,L,Lz)
                if len(args[0]) == 1:
                    E = args[0][0]
                    L,Lz = None,None
                elif len(args[0]) == 2:
                    E,L = args[0]
                    Lz = None
                elif len(args[0]) == 3:
                    E,L,Lz = args[0]
            else: # Orbit
                E = args[0].E(pot=self._pot)
                L = numpy.sqrt(numpy.sum(numpy.square(args[0].L())))
                Lz = args[0].Lz()
            E= conversion.parse_energy(E,vo=self._vo)
            L= conversion.parse_angmom(L,ro=self._vo,vo=self._vo)
            Lz= conversion.parse_angmom(Lz,ro=self._vo,vo=self._vo)
        else: # Assume R,vR,vT,z,vz,(phi)
            if len(args) == 5:
                R,vR,vT,z,vz = args
                phi = None
            else:
                R,vR,vT,z,vz,phi = args
            R= conversion.parse_length(R,ro=self._ro)
            vR= conversion.parse_velocity(vR,vo=self._vo)
            vT= conversion.parse_velocity(vT,vo=self._vo)
            z= conversion.parse_length(z,ro=self._ro)
            vz= conversion.parse_velocity(vz,vo=self._vo)
            phi= conversion.parse_angle(phi)
            vtotSq = vR**2.+vT**2.+vz**2.
            E = 0.5*vtotSq + evaluatePotentials(R,z)
            Lz = R*vT
            r = numpy.sqrt(R**2.+z**2.)
            vrad = (R*vR+z*vz)/r
            L = numpy.sqrt(vtotSq-vrad**2.)*r
        f = self._call_internal(E,L,Lz) # Some function for each sub-class
        return f

############################### SAMPLING THE DF################################
    def sample(self,R=None,z=None,phi=None,n=1,return_orbit=True):
        """
        NAME:

            sample

        PURPOSE:

            Return full 6D samples of the DF

        INPUT:

            R= Radius at which to generate samples (can be Quantity)

            z= Height at which to generate samples (can be Quantity)
            
            phi= Azimuth at which to generate samples (can be Quantity)

            n= number of samples to generate

        OPTIONAL INPUT:

            return_orbit= If True output is orbit.Orbit object, if False 
                output is (R,vR,vT,z,vz,phi)

        OUTPUT:

            List of samples. Either vector (R,vR,vT,z,vz,phi) or orbit.Orbit

        NOTES:

            If R,z,phi are None then sample positions with CMF. If R,z,phi are 
            floats then sample n velocities at location. If array then sample 
            velocities at radii, ignoring n. phi can be None if R,z are set 
            by any above mechanism, will then sample phi for output.

        HISTORY:

            2020-07-22 - Written - Lane (UofT)

        """
        if R is None or z is None: # Full 6D samples
            r = self._sample_r(n=n)
            phi,theta = self._sample_position_angles(n=n)
            R = r*numpy.sin(theta)
            z = r*numpy.cos(theta) 
        else: # 3D velocity samples
            if isinstance(R,numpy.ndarray):
                assert len(R) == len(z)
                n = len(R)
            r = numpy.sqrt(R**2.+z**2.)
            if phi is None: # Otherwise assume phi input type matches R,z
                phi,_ = self._sample_position_angles(n=n)
        v = self._sample_v(r,n=n)
        eta,psi = self._sample_velocity_angles(n=n)
        vr = v*numpy.cos(eta)
        vtheta = v*numpy.sin(eta)*numpy.cos(psi)
        vT = v*numpy.sin(eta)*numpy.sin(psi)
        vR = vr*numpy.sin(theta) + vtheta*numpy.cos(theta)
        vz = vr*numpy.cos(theta) - vtheta*numpy.sin(theta)
        
        if return_orbit:
            o = Orbit(vxvv=numpy.array([R,vR,vT,z,vz,phi]).T)
            if self._roSet and self._voSet:
                o.turn_physical_on(ro=self._ro,vo=self._vo)
            return o
        else:
            return (R,vR,vT,z,vz,phi)

    def _sample_r(self,n=1):
        """Generate radial position samples from potential
        Note - the function interpolates the normalized CMF onto the variable 
        xi defined as:
        
        .. math:: \\xi = \\frac{r/a-1}{r/a+1}
        
        so that xi is in the range [-1,1], which corresponds to an r range of 
        [0,infinity)"""
        rand_mass_frac = numpy.random.uniform(size=n)
        if hasattr(self,'_icmf'):
            r_samples = self._icmf(rand_mass_frac)
        else:
            xi_samples = self._xi_cmf_interpolator(rand_mass_frac)
            r_samples = _xiToR(xi_samples,a=self._scale)
        return r_samples

    def _make_cmf_interpolator(self):
        """Create the interpolator object for calculating radii from the CMF
        Note - must use self.xi_to_r() on any output of interpolator
        Note - the function interpolates the normalized CMF onto the variable 
        xi defined as:
        
        .. math:: \\xi = \\frac{r-1}{r+1}
        
        so that xi is in the range [-1,1], which corresponds to an r range of 
        [0,infinity)"""
        xis = numpy.arange(-1,1,1e-6)
        rs = _xiToR(xis,a=self._scale)
        ms = self._pot.mass(rs,use_physical=False)
        ms /= self._pot.mass(10**12,use_physical=False)
        # Add total mass point
        xis = numpy.append(xis,1)
        ms = numpy.append(ms,1)
        return scipy.interpolate.InterpolatedUnivariateSpline(ms,xis,k=3)

    def _sample_position_angles(self,n=1):
        """Generate spherical angle samples"""
        phi_samples = numpy.random.uniform(size=n)*2*numpy.pi
        theta_samples = numpy.arccos(1.-2*numpy.random.uniform(size=n))
        return phi_samples,theta_samples

    def _sample_v(self,r,n=1):
        """Generate velocity samples"""
        return self._v_vesc_pvr_interpolator(\
                    numpy.log10(r/self._scale),numpy.random.uniform(size=n),
                    grid=False)\
                *vesc(self._pot,r,use_physical=False)

    def _sample_velocity_angles(self,n=1):
        """Generate samples of angles that set radial vs tangential velocities"""
        eta_samples = self._sample_eta(n)
        psi_samples = numpy.random.uniform(size=n)*2*numpy.pi
        return eta_samples,psi_samples

    def _make_pvr_interpolator(self, r_a_start=-3, r_a_end=3, 
                               r_a_interval=0.05, v_vesc_interval=0.01):
        """
        NAME:

        _make_pvr_interpolator

        PURPOSE:

        Calculate a grid of the velocity sampling function v^2*f(E) over many 
        radii. The radii are fractional with respect to some scale radius 
        which characteristically describes the size of the potential, 
        and the velocities are fractional with respect to the escape velocity 
        at each radius r. This information is saved in a 2D interpolator which 
        represents the inverse cumulative distribution at many radii. This 
        allows for sampling of v/vesc given an input r/a

        INPUT:

            r_a_start= radius grid start location in units of r/a

            r_a_end= radius grid end location in units of r/a

            r_a_interval= radius grid spacing in units of r/a

            v_vesc_interval= velocity grid spacing in units of v/vesc

        OUTPUT:

            None (But sets self._v_vesc_pvr_interpolator)

        HISTORY:

            Written 2020-07-24 - James Lane (UofT)
        """
        # Make an array of r/a by v/vesc and then calculate p(v|r)
        r_a_values = 10.**numpy.arange(r_a_start,r_a_end,r_a_interval)
        v_vesc_values = numpy.arange(0,1,v_vesc_interval)
        r_a_grid, v_vesc_grid = numpy.meshgrid(r_a_values,v_vesc_values)
        vesc_grid = vesc(self._pot,r_a_grid*self._scale,use_physical=False)
        r_grid= r_a_grid*self._scale
        vr_grid= v_vesc_grid*vesc_grid
        # Calculate p(v|r) and normalize
        pvr_grid= self._p_v_at_r(vr_grid,r_grid)
        pvr_grid_cml = numpy.cumsum(pvr_grid,axis=0)
        pvr_grid_cml_norm = pvr_grid_cml\
        /numpy.repeat(pvr_grid_cml[-1,:][:,numpy.newaxis],pvr_grid_cml.shape[0],axis=1).T
        
        # Construct the inverse cumulative distribution on a regular grid
        n_new_pvr = 100 # Must be multiple of r_a_grid.shape[0]
        icdf_pvr_grid_reg = numpy.zeros((n_new_pvr,len(r_a_values)))
        icdf_v_vesc_grid_reg = numpy.zeros((n_new_pvr,len(r_a_values)))
        for i in range(pvr_grid_cml_norm.shape[1]):
            cml_pvr = pvr_grid_cml_norm[:,i]
            # Deal with the fact that the escape velocity might be beyond
            # allowed velocities for the DF (e.g., King, where any start that
            # escapes to r > rt is unbound, but v_esc is still defined by the
            # escape to infinity)
            try:
                end_indx= numpy.amin(numpy.arange(len(cml_pvr))[cml_pvr == numpy.amax(cml_pvr)])+1
            except ValueError:
                end_indx= len(cml_pvr)
            cml_pvr_inv_interp = scipy.interpolate.InterpolatedUnivariateSpline(cml_pvr[:end_indx], 
                v_vesc_values[:end_indx],k=3)
            pvr_samples_reg = numpy.linspace(0,1,n_new_pvr)
            v_vesc_samples_reg = cml_pvr_inv_interp(pvr_samples_reg)
            icdf_pvr_grid_reg[:,i] = pvr_samples_reg
            icdf_v_vesc_grid_reg[:,i] = v_vesc_samples_reg
        # Create the interpolator
        return scipy.interpolate.RectBivariateSpline(
            numpy.log10(r_a_grid[0,:]), icdf_pvr_grid_reg[:,0],
            icdf_v_vesc_grid_reg.T)

class isotropicsphericaldf(sphericaldf):
    """Superclass for isotropic spherical distribution functions"""
    def __init__(self,ro=None,vo=None):
        """
        NAME:

            __init__

        PURPOSE:

            Initialize an isotropic distribution function

        INPUT:

           ro=, vo= galpy unit parameters

        OUTPUT:
        
            None

        HISTORY:

            2020-09-02 - Written - Bovy (UofT)

        """
        sphericaldf.__init__(self,ro=ro,vo=vo)

    def _sample_eta(self,n=1):
        """Sample the angle eta which defines radial vs tangential velocities"""
        return numpy.arccos(1.-2.*numpy.random.uniform(size=n))

    def _p_v_at_r(self,v,r):
        return self.fE(evaluatePotentials(self._pot,r,0,use_physical=False)\
                       +0.5*v**2.)*v**2.
    
class anisotropicsphericaldf(sphericaldf):
    """Superclass for anisotropic spherical distribution functions"""
    def __init__(self,ro=None,vo=None):
        """
        NAME:

            __init__

        PURPOSE:

            Initialize an anisotropic distribution function

        INPUT:

           ro= ,vo= galpy unit parameters

        OUTPUT:
        
            None

        HISTORY:

            2020-07-22 - Written - 

        """
        sphericaldf.__init__(self,ro=ro,vo=vo)
